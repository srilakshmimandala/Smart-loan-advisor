// API Base URL
const BASE_URL = '';

// Global Chart variables for dashboard updates
let emiChartInstance = null;
let costBreakdownChartInstance = null;

const loanEmojis = {
  "Home Loan": "🏠",
  "Personal Loan": "💰",
  "Car Loan": "🚗",
  "Vehicle Loan": "🚗",
  "Auto Loan": "🚗",
  "Education Loan": "🎓",
  "Gold Loan": "💍",
  "Business Loan": "💼"
};

function getLoanEmoji(type, withSpan = true) {
  if (!type) return "";
  const t = type.toLowerCase();
  let emoji = "";
  if (t.includes("home")) emoji = "🏠";
  else if (t.includes("personal")) emoji = "💰";
  else if (t.includes("car") || t.includes("vehicle") || t.includes("auto")) emoji = "🚗";
  else if (t.includes("education")) emoji = "🎓";
  else if (t.includes("gold")) emoji = "💍";
  else if (t.includes("business")) emoji = "💼";
  
  if (!emoji) return "";
  return withSpan ? `<span class="loan-emoji">${emoji}</span>` : emoji;
}

// Parse amount written in natural language (e.g. "12 thousand", "5 lakh", "50k", "1 crore")
function parseAmount(text) {
  if (typeof text !== 'string') return NaN;
  let cleanText = text.replace(/[₹$,]/g, '').trim().toLowerCase();
  
  const match = cleanText.match(/^([0-9]+(?:\.[0-9]+)?)\s*(thousand|k|lakhs?|lacs?|crores?|cr)$/);
  if (match) {
    const value = parseFloat(match[1]);
    const unit = match[2];
    
    if (unit === 'thousand' || unit === 'k') {
      return value * 1000;
    } else if (unit === 'lakh' || unit === 'lacs' || unit === 'lakhs' || unit === 'lac') {
      return value * 100000;
    } else if (unit === 'crore' || unit === 'cr' || unit === 'crores') {
      return value * 10000000;
    }
  }
  
  return parseFloat(cleanText);
}

// ==========================================
// 1. CHAT INTAKE FLOW (chat.html)
// ==========================================

let chatState = {
  step: 0,
  data: {
    name: '',
    age: null,
    city: '',
    employment_type: '',
    monthly_income: null,
    existing_emis: null,
    credit_score: null, // number or "Unknown"
    loan_purpose: '',
    desired_amount: null,
    preferred_tenure: null,
    has_collateral: false,
    credit_estimator_answers: {}
  },
  estimatorStep: 0
};

// Credit Estimator Questions
const ESTIMATOR_QUESTIONS = [
  {
    key: 'payment_history',
    text: "How would you rate your credit card and loan payment history?",
    options: ["Always on time", "Sometimes late", "Frequently late/defaults"]
  },
  {
    key: 'accounts_count',
    text: "How many active credit cards or loan accounts do you currently have?",
    options: ["None", "1-2", "3-5", "6+"]
  },
  {
    key: 'utilization',
    text: "What percentage of your credit card limits do you typically utilize?",
    options: ["Below 30%", "30% - 50%", "Over 50%"]
  },
  {
    key: 'defaults',
    text: "Have you ever defaulted or had a loan account written off?",
    options: ["No", "Yes"]
  },
  {
    key: 'employment_years',
    text: "How long have you been in your current line of employment or business?",
    options: ["Less than 1 year", "1-2 years", "2-5 years", "5+ years"]
  },
  {
    key: 'inquiries',
    text: "Have you made any hard credit inquiries in the last 6 months?",
    options: ["None", "1-2 inquiries", "3+ inquiries"]
  }
];

function initChatFlow() {
  const chatBox = document.getElementById("chatBox");
  if (!chatBox) return; // Not on chat page

  // Clear chat box
  chatBox.innerHTML = '';
  
  // Set up event listeners
  const sendBtn = document.getElementById("sendBtn");
  const userInput = document.getElementById("userInput");
  
  sendBtn.addEventListener("click", handleUserMessage);
  userInput.addEventListener("keypress", (e) => {
    if (e.key === 'Enter') handleUserMessage();
  });
  
  // Bot greeting
  appendBotMessage("Welcome to Smart Loan Advisor! I'm your conversational financial guide. Let's gather your details to find the absolute best loan options for you.");
  setTimeout(() => {
    askNextQuestion();
  }, 800);
}

function appendBotMessage(text) {
  const chatBox = document.getElementById("chatBox");
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble bot";
  
  // Replace loan type names with emoji + loan type
  let decoratedText = text;
  const terms = ["Home Loan", "Personal Loan", "Car Loan", "Vehicle Loan", "Education Loan", "Gold Loan", "Business Loan"];
  terms.forEach(term => {
    const regex = new RegExp(`\\b${term}\\b`, 'gi');
    decoratedText = decoratedText.replace(regex, (matched) => {
      const emojiSpan = getLoanEmoji(term, true);
      return emojiSpan ? `${emojiSpan}${matched}` : matched;
    });
  });
  
  bubble.innerHTML = decoratedText;
  chatBox.appendChild(bubble);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function appendUserMessage(text) {
  const chatBox = document.getElementById("chatBox");
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble user";
  bubble.innerHTML = text;
  chatBox.appendChild(bubble);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function showQuickReplies(options, onSelect) {
  const container = document.getElementById("quickReplies");
  container.innerHTML = '';
  container.style.display = "flex";
  
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.className = "reply-btn";
    btn.innerHTML = opt;
    btn.onclick = () => {
      container.style.display = "none";
      onSelect(opt);
    };
    container.appendChild(btn);
  });
}

function updateProgressBar(percentage) {
  const progressBar = document.getElementById("progressBar");
  if (progressBar) {
    progressBar.style.width = percentage + "%";
  }
}

function askNextQuestion() {
  const totalSteps = 11;
  updateProgressBar((chatState.step / totalSteps) * 100);
  
  switch(chatState.step) {
    case 0:
      appendBotMessage("First, what is your full name?");
      break;
    case 1:
      appendBotMessage(`Great to meet you, ${chatState.data.name}! How old are you?`);
      break;
    case 2:
      appendBotMessage("Which city do you reside in?");
      break;
    case 3:
      appendBotMessage("What is your employment status?");
      showQuickReplies(["Salaried", "Self-Employed", "Freelancer", "Business Owner"], (val) => {
        appendUserMessage(val);
        chatState.data.employment_type = val;
        chatState.step++;
        askNextQuestion();
      });
      break;
    case 4:
      appendBotMessage("What is your monthly gross income (in INR)?");
      break;
    case 5:
      appendBotMessage("What are your total monthly debt payments (existing EMIs) in INR? Enter 0 if none.");
      break;
    case 6:
      appendBotMessage("Do you know your credit score? If not, click 'Estimate Score'.");
      showQuickReplies(["Enter Score", "Estimate Score"], (val) => {
        appendUserMessage(val);
        if (val === "Estimate Score") {
          chatState.data.credit_score = "Unknown";
          // Transition into estimator
          runCreditEstimator();
        } else {
          // Ask for credit score value
          appendBotMessage("Please enter your credit score (between 300 and 850):");
          // Temporary flag to catch score in userInput
          chatState.enteringScore = true;
        }
      });
      break;
    case 7:
      appendBotMessage("What type of loan are you looking for?");
      showQuickReplies([
        '<span class="loan-emoji">🏠</span>Home Loan',
        '<span class="loan-emoji">💰</span>Personal Loan',
        '<span class="loan-emoji">🚗</span>Car Loan',
        '<span class="loan-emoji">🎓</span>Education Loan'
      ], (val) => {
        appendUserMessage(val);
        // Strip the HTML and emoji before saving
        chatState.data.loan_purpose = val.replace(/<[^>]*>/g, '').replace(/[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF]/g, '').trim();
        chatState.step++;
        askNextQuestion();
      });
      break;
    case 8:
      appendBotMessage("What is your desired loan amount in INR?");
      break;
    case 9:
      appendBotMessage("What is your preferred tenure in years?");
      break;
    case 10:
      appendBotMessage("Do you have collateral to offer? (e.g. property, FD, gold)");
      showQuickReplies(["Yes", "No"], (val) => {
        appendUserMessage(val);
        chatState.data.has_collateral = (val === "Yes");
        chatState.step++;
        submitIntakeForm();
      });
      break;
  }
}

function runCreditEstimator() {
  if (chatState.estimatorStep < ESTIMATOR_QUESTIONS.length) {
    const q = ESTIMATOR_QUESTIONS[chatState.estimatorStep];
    appendBotMessage(`[Estimator] Question ${chatState.estimatorStep + 1}/6: ${q.text}`);
    showQuickReplies(q.options, (val) => {
      appendUserMessage(val);
      chatState.data.credit_estimator_answers[q.key] = val;
      chatState.estimatorStep++;
      runCreditEstimator();
    });
  } else {
    // Estimator finished, proceed to loan purpose question
    appendBotMessage("Thank you! Based on your behavioral indicators, we'll estimate your credit score via our risk analyzer.");
    chatState.step = 7; // Go to loan purpose
    setTimeout(() => askNextQuestion(), 1000);
  }
}

function handleUserMessage() {
  const inputEl = document.getElementById("userInput");
  const val = inputEl.value.trim();
  if (!val) return;
  
  appendUserMessage(val);
  inputEl.value = '';
  
  // If we are currently entering credit score numerically
  if (chatState.enteringScore) {
    const score = parseInt(val);
    if (isNaN(score) || score < 300 || score > 850) {
      appendBotMessage("Please enter a valid credit score integer between 300 and 850.");
      return;
    }
    chatState.data.credit_score = score;
    chatState.enteringScore = false;
    chatState.step = 7; // proceed to loan purpose
    setTimeout(() => askNextQuestion(), 800);
    return;
  }

  // Handle standard questions
  switch(chatState.step) {
    case 0:
      chatState.data.name = val;
      chatState.step++;
      askNextQuestion();
      break;
    case 1:
      const age = parseInt(val);
      if (isNaN(age) || age < 18 || age > 100) {
        appendBotMessage("Please enter a valid age (18 or older).");
        return;
      }
      chatState.data.age = age;
      chatState.step++;
      askNextQuestion();
      break;
    case 2:
      chatState.data.city = val;
      chatState.step++;
      askNextQuestion();
      break;
    case 4:
      const income = parseAmount(val);
      if (isNaN(income) || income <= 0) {
        appendBotMessage("Please enter a valid monthly income number.");
        return;
      }
      chatState.data.monthly_income = income;
      chatState.step++;
      askNextQuestion();
      break;
    case 5:
      const emis = parseAmount(val);
      if (isNaN(emis) || emis < 0) {
        appendBotMessage("Please enter a valid EMI amount (or 0).");
        return;
      }
      chatState.data.existing_emis = emis;
      chatState.step++;
      askNextQuestion();
      break;
    case 8:
      const amount = parseAmount(val);
      if (isNaN(amount) || amount <= 0) {
        appendBotMessage("Please enter a valid desired amount.");
        return;
      }
      chatState.data.desired_amount = amount;
      chatState.step++;
      askNextQuestion();
      break;
    case 9:
      const tenure = parseInt(val);
      if (isNaN(tenure) || tenure <= 0) {
        appendBotMessage("Please enter a valid preferred tenure (in years).");
        return;
      }
      chatState.data.preferred_tenure = tenure;
      chatState.step++;
      askNextQuestion();
      break;
  }
}

async function submitIntakeForm() {
  updateProgressBar(100);
  
  // Show loader overlay
  const overlay = document.getElementById("loaderOverlay");
  const loaderText = document.getElementById("loaderText");
  const loaderSubtext = document.getElementById("loaderSubtext");
  
  overlay.classList.add("active");
  
  // Sequence of agent status logs for rich UX feedback
  let stepIdx = 0;
  const statuses = [
    { text: "Structuring Financial Profile...", sub: "Agent 1: Sanitizing variables and verifying inputs..." },
    { text: "Verifying Credit Policy rules...", sub: "Agent 2: Checking age, income, and DTI caps..." },
    { text: "Performing Side-by-Side Comparison...", sub: "Agent 3: Calculating EMIs, EARs, and APRs..." },
    { text: "Advising Suitability Scores...", sub: "Agent 4: Structuring fit rankings and negotiation tips..." },
    { text: "Compiling Premium PDF Document...", sub: "Agent 5: Creating the final 5-page report layout..." }
  ];
  
  const statusTimer = setInterval(() => {
    if (stepIdx < statuses.length - 1) {
      stepIdx++;
      loaderText.innerText = statuses[stepIdx].text;
      loaderSubtext.innerText = statuses[stepIdx].sub;
    }
  }, 3500);

  try {
    // 1. Submit Intake Profile
    const intakeRes = await fetch(`${BASE_URL}/api/customer/intake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatState.data)
    });
    
    if (!intakeRes.ok) {
      const err = await intakeRes.json();
      throw new Error(err.message || "Failed intake submission.");
    }
    
    const intakeData = await intakeRes.json();
    const customerId = intakeData.customer_id;
    
    // 2. Trigger Sequential CrewAI Pipeline
    const pipelineRes = await fetch(`${BASE_URL}/api/run-pipeline`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_id: customerId })
    });
    
    if (!pipelineRes.ok) {
      const err = await pipelineRes.json();
      throw new Error(err.message || "Failed pipeline execution.");
    }
    
    // Save customer id and redirect
    localStorage.setItem("currentCustomerId", customerId);
    clearInterval(statusTimer);
    
    loaderText.innerText = "Analysis Complete!";
    loaderSubtext.innerText = "Redirecting to your Smart Loan Advisor Dashboard...";
    
    setTimeout(() => {
      window.location.href = 'index.html';
    }, 1500);
    
  } catch (error) {
    clearInterval(statusTimer);
    overlay.classList.remove("active");
    appendBotMessage(`Error: ${error.message}. Please refresh the page and try again.`);
  }
}

// ==========================================
// 2. DASHBOARD CONTROLLER (index.html)
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
  const dashboardContent = document.getElementById("dashboardContent");
  if (!dashboardContent) return; // Not on dashboard page
  
  const customerId = localStorage.getItem("currentCustomerId");
  if (!customerId) {
    // No active customer profile
    document.getElementById("emptyState").style.display = "block";
    loadHistorySessions();
  } else {
    document.getElementById("emptyState").style.display = "none";
    dashboardContent.style.display = "block";
    loadDashboardData(customerId);
  }
});

async function loadDashboardData(customerId) {
  try {
    // 1. Fetch Profile
    const profileRes = await fetch(`${BASE_URL}/api/customer/${customerId}`);
    const profileData = await profileRes.json();
    if (profileData.status !== "success") {
      throw new Error(profileData.message);
    }
    const profile = profileData.profile;
    window.currentProfile = profile;
    
    // Populate profile details
    document.getElementById("clientName").innerText = profile.name;
    document.getElementById("clientMeta").innerText = `Age: ${profile.age} | City: ${profile.city} | Employment: ${profile.employment_type}`;
    document.getElementById("clientCreditScore").innerText = profile.credit_score;
    
    // Update dashboard title based on loan purpose
    const purpose = profile.loan_purpose || "Loan";
    document.title = `Smart Loan Advisor — ${purpose} Dashboard`;
    const recsTitle = document.getElementById("recommendationsTitle");
    if (recsTitle) {
      recsTitle.innerHTML = `Top ${purpose} Recommendations <span>Tailored Matches</span>`;
    }
    
    // Update credit score gauge ring rotation
    const scorePct = ((profile.credit_score - 300) / 550) * 100;
    const ring = document.getElementById("scoreRing");
    let scoreColor = "var(--color-conditional)";
    if (profile.credit_score >= 750) scoreColor = "var(--color-eligible)";
    if (profile.credit_score < 600) scoreColor = "var(--color-rejected)";
    ring.style.background = `conic-gradient(${scoreColor} ${scorePct}%, rgba(255,255,255,0.05) ${scorePct}%)`;
    
    // Set up PDF download link
    const pdfBtn = document.getElementById("downloadReportBtn");
    pdfBtn.onclick = () => {
      window.location.href = `${BASE_URL}/api/report/${customerId}`;
    };

    // 2. Fetch recommendations & comparisons
    const recsRes = await fetch(`${BASE_URL}/api/recommendations/${customerId}`);
    const recsData = await recsRes.json();
    
    const compRes = await fetch(`${BASE_URL}/api/comparison/${customerId}`);
    const compData = await compRes.json();
    
    console.log("recsData:", recsData);
    console.log("compData:", compData);
    
    if (recsRes.ok && compRes.ok) {
      let compList = [];
      if (compData.comparisons) {
        if (Array.isArray(compData.comparisons)) {
          compList = compData.comparisons;
        } else if (Array.isArray(compData.comparisons.comparisons)) {
          compList = compData.comparisons.comparisons;
        }
      }
      window.originalEligibility = recsData.eligibility || {};
      window.originalRecommendations = recsData.recommendations || {};
      window.originalComparisons = compList;
      populateRecommendations(recsData.recommendations || {}, compList, customerId);
      populateEligibility(recsData.eligibility || {});
      renderCharts(compList);
    } else {
      document.getElementById("recommendationsContainer").innerHTML = `
        <div class="rec-card glass-panel rank-1" style="text-align: center; color: var(--text-secondary);">
          Failed to load recommendations. Please run intake pipeline again.
        </div>
      `;
    }

    // 3. Setup Kanban board
    loadKanbanBoard(customerId);
    
    // 4. Setup calculators & simulators
    initInteractiveCalculator(profile);
    initWhatIfSimulator(profile, customerId);
    
    // 5. Load improvement recommendations
    loadImprovementPlan(customerId);
    
    // 6. Refresh global history list
    loadHistorySessions();
    
  } catch (error) {
    console.error("Dashboard load failed:", error);
  }
}

function populateEligibility(eligibilityData) {
  const grid = document.getElementById("eligibilityGrid");
  if (!grid) return;
  
  grid.innerHTML = '';
  
  const displayCategories = [
    { label: '<span class="loan-emoji">🏠</span>Home Loan', dbKeys: ["Home Loan", "Home"] },
    { label: '<span class="loan-emoji">💰</span>Personal Loan', dbKeys: ["Personal Loan", "Personal"] },
    { label: '<span class="loan-emoji">🚗</span>Auto Loan', dbKeys: ["Car Loan", "Vehicle Loan", "Vehicle"] },
    { label: '<span class="loan-emoji">🎓</span>Education Loan', dbKeys: ["Education Loan", "Education"] }
  ];
  
  const typeEligibility = eligibilityData.loan_type_eligibility || {};
  
  displayCategories.forEach(cat => {
    const card = document.createElement("div");
    card.className = "eligibility-card glass-panel";
    
    let status = "Not Eligible";
    let statusClass = "rejected";
    
    let details = null;
    for (const key of cat.dbKeys) {
      if (typeEligibility[key]) {
        details = typeEligibility[key];
        break;
      }
    }
    
    if (details) {
      let match = "";
      if (typeof details === "string") {
        match = details.toLowerCase();
      } else if (typeof details === "object" && details !== null) {
        match = (details.status || "").toLowerCase();
      }
      
      if (match === "eligible") {
        status = "Eligible";
        statusClass = "eligible";
      } else if (match && match.includes("conditional")) {
        status = "Conditional";
        statusClass = "conditional";
      }
    }
    
    card.innerHTML = `
      <h4>${cat.label}</h4>
      <span class="badge ${statusClass}">${status}</span>
    `;
    grid.appendChild(card);
  });
}

function populateRecommendations(recsObj, comparisonsList, customerId) {
  const container = document.getElementById("recommendationsContainer");
  container.innerHTML = '';
  
  const list = recsObj.recommendations || [];
  if (list.length === 0) {
    container.innerHTML = `
      <div class="rec-card glass-panel rank-1" style="text-align: center; color: var(--text-secondary); padding: 30px;">
        No suitable loan recommendations found based on criteria.
      </div>
    `;
    return;
  }
  
  list.forEach((rec) => {
    // Find financial calculations from comparison list matching loan_id
    const comp = comparisonsList.find(c => c.loan_id === rec.loan_id) || {};
    
    const card = document.createElement("div");
    card.className = `rec-card glass-panel rank-${rec.rank}`;
    
    // Formatted numbers
    const emiVal = comp.monthly_emi ? `₹${Math.round(comp.monthly_emi).toLocaleString()}` : "N/A";
    const rateVal = comp.interest_rate_used ? `${comp.interest_rate_used}%` : "N/A";
    const tenureVal = comp.tenure_months ? `${comp.tenure_months / 12} Years` : "N/A";
    
    const advantagesList = (rec.advantages || []).map(adv => `<li>${adv}</li>`).join("");
    const risksList = (rec.risks || []).map(risk => `<li>${risk}</li>`).join("");
    
    const emojiSpan = getLoanEmoji(rec.loan_type, true);
    const typeLabel = emojiSpan ? `${emojiSpan}${rec.loan_type}` : rec.loan_type;

    card.innerHTML = `
      <div class="rec-card-header">
        <div class="rec-bank">
          <h3>${rec.bank_name}</h3>
          <p>${typeLabel} — Rank #${rec.rank}</p>
        </div>
        <div class="suitability-badge">
          Match ${rec.suitability_score}%
        </div>
      </div>
      
      <p class="rec-body-text">${rec.why_suits}</p>
      
      <div class="rec-key-details">
        <div class="detail-item">
          <p>INTEREST RATE</p>
          <h4>${rateVal}</h4>
        </div>
        <div class="detail-item">
          <p>ESTIMATED EMI</p>
          <h4>${emiVal}</h4>
        </div>
        <div class="detail-item">
          <p>TENURE</p>
          <h4>${tenureVal}</h4>
        </div>
      </div>
      
      <button class="rec-expandable-btn" onclick="toggleDetailsPanel(this)">
        <i class="fa-solid fa-chevron-down"></i> View Detailed Advisory & Apply
      </button>
      
      <div class="rec-details-panel">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 16px;">
          <div>
            <h5 style="font-size: 13px; color: var(--accent-gold); margin-bottom: 8px;">Key Advantages</h5>
            <ul class="rec-bullet-list">
              ${advantagesList}
            </ul>
          </div>
          <div>
            <h5 style="font-size: 13px; color: var(--color-rejected); margin-bottom: 8px;">Critical Risks</h5>
            <ul class="rec-bullet-list">
              ${risksList}
            </ul>
          </div>
        </div>
        
        <div class="advice-card" style="margin-bottom: 16px;">
          <strong>Suggested Tenure:</strong> ${rec.suggested_tenure}<br>
          <strong>Negotiation Strategy:</strong> ${rec.negotiation_tip}
        </div>
        
        <button class="primary-btn" style="width: 100%; justify-content: center; font-size: 13px; padding: 10px 18px;" 
                onclick="applyForLoan(${customerId}, '${rec.loan_id}', '${rec.bank_name}', '${rec.loan_type}')">
          <i class="fa-solid fa-paper-plane"></i> Apply for this Loan Product
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function toggleDetailsPanel(btn) {
  const panel = btn.nextElementSibling;
  const icon = btn.querySelector("i");
  
  if (panel.classList.contains("active")) {
    panel.classList.remove("active");
    icon.className = "fa-solid fa-chevron-down";
  } else {
    panel.classList.add("active");
    icon.className = "fa-solid fa-chevron-up";
  }
}

// Kanban Status updates
async function applyForLoan(customerId, loanId, bankName, loanType) {
  const bankUrls = {
    "SBI": "https://sbi.co.in",
    "HDFC": "https://www.hdfcbank.com",
    "ICICI": "https://www.icicibank.com",
    "Axis": "https://www.axisbank.com",
    "Kotak": "https://www.kotak.com",
    "Bajaj Finserv": "https://www.bajajfinserv.in",
    "Bank of Baroda": "https://www.bankofbaroda.in",
    "Muthoot Finance": "https://www.muthootfinance.com",
    "HDFC Credila": "https://www.hdfccredila.com"
  };
  
  const url = bankUrls[bankName] || "https://google.com";
  window.open(url, '_blank');
  
  try {
    const res = await fetch(`${BASE_URL}/api/loans/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer_id: customerId,
        loan_id: loanId,
        bank_name: bankName,
        loan_type: loanType,
        status: 'Applied'
      })
    });
    
    if (res.ok) {
      alert(`Application sent! Mock application for ${bankName} has been tracked to 'Applied' column and the official page has been opened.`);
      loadKanbanBoard(customerId);
    } else {
      alert("Failed to submit loan application tracker.");
    }
  } catch (error) {
    console.error("Error applying for loan:", error);
  }
}

async function loadKanbanBoard(customerId) {
  try {
    const res = await fetch(`${BASE_URL}/api/loans/tracker/${customerId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);
    
    const apps = data.applications || [];
    
    // Clear all lanes
    const columns = ["Applied", "Under Review", "Approved", "Rejected"];
    columns.forEach(col => {
      const container = document.querySelector(`#kanban-${col.replace(/ /g, '\\ ')} .kanban-cards-container`);
      if (container) container.innerHTML = '';
    });
    
    if (apps.length === 0) {
      // Put placeholder in Applied
      const container = document.querySelector(`#kanban-Applied .kanban-cards-container`);
      if (container) {
        container.innerHTML = `
          <div style="text-align: center; color: var(--text-muted); font-size: 11px; padding: 20px; border: 1px dashed var(--border-glass); border-radius: 8px;">
            No active applications. Select a recommendation and click 'Apply'.
          </div>
        `;
      }
      return;
    }
    
    apps.forEach(app => {
      const colId = `kanban-${app.status}`;
      const container = document.getElementById(colId)?.querySelector(".kanban-cards-container");
      if (!container) return;
      
      const card = document.createElement("div");
      card.className = "kanban-card";
      card.setAttribute("draggable", "true");
      
      // Setup drag events
      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", JSON.stringify({
          customerId: customerId,
          loanId: app.loan_id,
          bankName: app.bank_name,
          loanType: app.loan_type
        }));
      });
      
      // Status transition choices
      let nextStatus = '';
      let btnLabel = '';
      if (app.status === 'Applied') {
        nextStatus = 'Under Review';
        btnLabel = 'Review';
      } else if (app.status === 'Under Review') {
        nextStatus = 'Approved';
        btnLabel = 'Approve';
      } else if (app.status === 'Approved') {
        nextStatus = 'Rejected';
        btnLabel = 'Reject';
      } else if (app.status === 'Rejected') {
        nextStatus = 'Applied';
        btnLabel = 'Re-apply';
      }
      
      const emojiSpan = getLoanEmoji(app.loan_type, true);
      const typeLabel = emojiSpan ? `${emojiSpan}${app.loan_type}` : app.loan_type;

      card.innerHTML = `
        <h5>${app.bank_name}</h5>
        <p>${typeLabel}</p>
        <div class="kanban-actions">
          <button class="kanban-btn" onclick="updateAppStatus(${customerId}, '${app.loan_id}', '${app.bank_name}', '${app.loan_type}', '${nextStatus}')">
            ${btnLabel} <i class="fa-solid fa-arrow-right"></i>
          </button>
        </div>
      `;
      container.appendChild(card);
    });
    
    // Set up drop zones on lanes
    columns.forEach(col => {
      const column = document.getElementById(`kanban-${col}`);
      if (!column) return;
      
      column.addEventListener("dragover", (e) => {
        e.preventDefault();
      });
      
      column.addEventListener("drop", async (e) => {
        e.preventDefault();
        try {
          const dragData = JSON.parse(e.dataTransfer.getData("text/plain"));
          await updateAppStatus(dragData.customerId, dragData.loanId, dragData.bankName, dragData.loanType, col);
        } catch (err) {
          console.error("Drop error:", err);
        }
      });
    });
    
  } catch (error) {
    console.error("Kanban failed:", error);
  }
}

async function updateAppStatus(customerId, loanId, bankName, loanType, newStatus) {
  try {
    const res = await fetch(`${BASE_URL}/api/loans/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer_id: customerId,
        loan_id: loanId,
        bank_name: bankName,
        loan_type: loanType,
        status: newStatus
      })
    });
    if (res.ok) {
      loadKanbanBoard(customerId);
    }
  } catch (error) {
    console.error("Failed to update status:", error);
  }
}

// Chart.js Visualizer
function renderCharts(comparisons) {
  const emiCtx = document.getElementById("emiChart")?.getContext("2d");
  const costCtx = document.getElementById("costBreakdownChart")?.getContext("2d");
  
  if (!emiCtx || !costCtx) return;
  
  // Destroy old instances
  if (emiChartInstance) emiChartInstance.destroy();
  if (costBreakdownChartInstance) costBreakdownChartInstance.destroy();
  
  const labels = comparisons.map(c => c.bank_name);
  const emis = comparisons.map(c => c.monthly_emi);
  const totalInterests = comparisons.map(c => c.total_interest);
  const principals = comparisons.map(c => c.total_amount_payable - c.total_interest); // essentially simulated principal
  
  // Chart.js global theme defaults
  Chart.defaults.color = '#9ca3af';
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
  
  // EMI Comparison Bar Chart
  emiChartInstance = new Chart(emiCtx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Monthly EMI (INR)',
        data: emis,
        backgroundColor: 'rgba(0, 242, 254, 0.7)',
        borderColor: '#00f2fe',
        borderWidth: 1,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { callback: value => '₹' + value.toLocaleString() }
        },
        x: { grid: { display: false } }
      },
      plugins: {
        legend: { display: false }
      }
    }
  });
  
  // Stacked Cost Breakdown Chart (Principal vs Interest)
  costBreakdownChartInstance = new Chart(costCtx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Principal Loan Amount',
          data: principals,
          backgroundColor: 'rgba(139, 92, 246, 0.65)',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          borderRadius: 4
        },
        {
          label: 'Total Interest Payable',
          data: totalInterests,
          backgroundColor: 'rgba(0, 242, 254, 0.7)',
          borderColor: '#00f2fe',
          borderWidth: 1,
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          stacked: true,
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { callback: value => '₹' + value.toLocaleString() }
        },
        x: {
          stacked: true,
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          position: 'top',
          labels: { boxWidth: 12 }
        }
      }
    }
  });
}

// Local EMI and DTI Live Estimator
function initInteractiveCalculator(profile) {
  const sAmount = document.getElementById("sliderAmount");
  const sRate = document.getElementById("sliderRate");
  const sTenure = document.getElementById("sliderTenure");
  
  const valAmount = document.getElementById("valAmount");
  const valRate = document.getElementById("valRate");
  const valTenure = document.getElementById("valTenure");
  
  const calcEmi = document.getElementById("calcEmi");
  const calcDti = document.getElementById("calcDti");
  
  // Defensive numeric coercion for profile fields
  const income = Number(String(profile.monthly_income).replace(/[₹$,]/g, '')) || 0;
  const existingEmis = Number(String(profile.existing_emis).replace(/[₹$,]/g, '')) || 0;
  
  function updateCalculatorValues() {
    const amount = parseFloat(sAmount.value);
    const rate = parseFloat(sRate.value);
    const tenureYears = parseInt(sTenure.value);
    
    // Labels
    valAmount.innerText = amount.toLocaleString('en-IN');
    valRate.innerText = rate + "%";
    valTenure.innerText = tenureYears + " Years";
    
    // Math
    const r = (rate / 12) / 100;
    const n = tenureYears * 12;
    let emi = 0;
    if (rate === 0) {
      emi = amount / n;
    } else {
      emi = amount * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
    }
    
    // Debug logging as requested
    console.log("[DTI Calculation] exact income value:", income, "typeof:", typeof income, "existingEmis:", existingEmis, "newEmi:", emi);
    
    const totalDti = income > 0 ? ((existingEmis + emi) / income) * 100 : 0;
    
    // Render
    calcEmi.innerText = "₹" + Math.round(emi).toLocaleString('en-IN');
    calcDti.innerText = totalDti.toFixed(1) + "%";
    if (totalDti > 50) {
      calcDti.style.color = "var(--color-rejected)";
    } else if (totalDti > 40) {
      calcDti.style.color = "var(--color-conditional)";
    } else {
      calcDti.style.color = "var(--color-eligible)";
    }
  }
  
  // Set default starting values matching user's intake preference
  const cleanDesiredAmount = Number(String(profile.desired_amount).replace(/[₹$,]/g, '')) || 500000;
  const cleanTenure = Number(profile.preferred_tenure) || 5;

  if (cleanDesiredAmount < parseFloat(sAmount.min)) {
    sAmount.min = Math.floor(cleanDesiredAmount / 100000) * 100000;
  }
  if (cleanDesiredAmount > parseFloat(sAmount.max)) {
    sAmount.max = Math.ceil(cleanDesiredAmount / 100000) * 100000;
  }
  sAmount.value = cleanDesiredAmount;
  sTenure.value = cleanTenure;
  
  sAmount.addEventListener("input", updateCalculatorValues);
  sRate.addEventListener("input", updateCalculatorValues);
  sTenure.addEventListener("input", updateCalculatorValues);
  
  updateCalculatorValues();
}

// "What-If" Scenario Simulator logic
function initWhatIfSimulator(profile, customerId) {
  const simIncome = document.getElementById("simIncome");
  const simAmount = document.getElementById("simAmount");
  const simTenure = document.getElementById("simTenure");
  
  const sValIncome = document.getElementById("simValIncome");
  const sValAmount = document.getElementById("simValAmount");
  const sValTenure = document.getElementById("simValTenure");
  
  const runBtn = document.getElementById("runSimBtn");
  const resetBtn = document.getElementById("resetSimBtn");
  
  function updateSliders() {
    sValIncome.innerText = "₹" + parseInt(simIncome.value).toLocaleString('en-IN');
    sValAmount.innerText = "₹" + parseInt(simAmount.value).toLocaleString('en-IN');
    sValTenure.innerText = simTenure.value + " Years";
  }
  
  // Bind defaults
  const cleanIncome = Number(String(profile.monthly_income).replace(/[₹$,]/g, '')) || 15000;
  const cleanDesiredAmount = Number(String(profile.desired_amount).replace(/[₹$,]/g, '')) || 500000;
  const cleanTenure = Number(profile.preferred_tenure) || 5;

  if (cleanIncome < parseFloat(simIncome.min)) {
    simIncome.min = Math.floor(cleanIncome / 1000) * 1000;
  }
  if (cleanIncome > parseFloat(simIncome.max)) {
    simIncome.max = Math.ceil(cleanIncome / 1000) * 1000;
  }
  simIncome.value = cleanIncome;

  if (cleanDesiredAmount < parseFloat(simAmount.min)) {
    simAmount.min = Math.floor(cleanDesiredAmount / 100000) * 100000;
  }
  if (cleanDesiredAmount > parseFloat(simAmount.max)) {
    simAmount.max = Math.ceil(cleanDesiredAmount / 100000) * 100000;
  }
  simAmount.value = cleanDesiredAmount;

  simTenure.value = cleanTenure;
  updateSliders();
  
  simIncome.addEventListener("input", updateSliders);
  simAmount.addEventListener("input", updateSliders);
  simTenure.addEventListener("input", updateSliders);
  
  runBtn.onclick = async () => {
    runBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Recalculating...`;
    
    try {
      const simulatedIncome = parseFloat(simIncome.value);
      const simulatedAmount = parseFloat(simAmount.value);
      const simulatedTenureYears = parseInt(simTenure.value);
      
      const res = await fetch(`${BASE_URL}/api/simulate-scenario`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile: window.currentProfile,
          simulated_income: simulatedIncome,
          simulated_amount: simulatedAmount,
          simulated_tenure_years: simulatedTenureYears
        })
      });
      
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.message);
      
      // Update UI elements
      document.getElementById("simResultBox").style.display = "block";
      document.getElementById("simResultDti").innerText = payload.eligibility.dti_ratio.toFixed(2) + "%";
      document.getElementById("simResultSummary").innerText = "With these changes, you qualify for " + (payload.eligibility.eligible_products ? payload.eligibility.eligible_products.length : 0) + " loan products";
      
      // Highlight DTI color
      const dtiEl = document.getElementById("simResultDti");
      if (payload.eligibility.dti_ratio > 50) {
        dtiEl.style.color = "var(--color-rejected)";
      } else if (payload.eligibility.dti_ratio > 40) {
        dtiEl.style.color = "var(--color-conditional)";
      } else {
        dtiEl.style.color = "var(--color-eligible)";
      }
      
      // Re-populate eligibility cards with simulated statuses
      if (payload.eligibility) {
        populateEligibility(payload.eligibility);
      }
      
      // Update Recommendations
      const compList = payload.comparisons ? (Array.isArray(payload.comparisons) ? payload.comparisons : (payload.comparisons.comparisons || [])) : [];
      populateRecommendations(payload.recommendations || {}, compList, customerId);
      
      // Refresh comparison charts with simulated comparisons
      if (compList && compList.length > 0) {
        renderCharts(compList);
      }
      
      // Show yellow "[Simulated]" label next to Eligibility section heading
      document.getElementById("simulatedLabel").style.display = "inline";
      
      // Show reset button
      resetBtn.style.display = "block";
      
      // List which loan types changed status
      function getEligibilityStatus(eligibilityObj, category) {
        const typeEligibility = eligibilityObj?.loan_type_eligibility || {};
        const dbKeys = {
          "Home Loan": ["Home Loan", "Home"],
          "Personal Loan": ["Personal Loan", "Personal"],
          "Vehicle Loan": ["Car Loan", "Vehicle Loan", "Vehicle"],
          "Education Loan": ["Education Loan", "Education"]
        }[category] || [category];
        
        let details = null;
        for (const key of dbKeys) {
          if (typeEligibility[key]) {
            details = typeEligibility[key];
            break;
          }
        }
        
        let status = "Not Eligible";
        if (details) {
          let match = "";
          if (typeof details === "string") {
            match = details.toLowerCase();
          } else if (typeof details === "object" && details !== null) {
            match = (details.status || "").toLowerCase();
          }
          
          if (match === "eligible") {
            status = "Eligible";
          } else if (match && match.includes("conditional")) {
            status = "Conditionally Eligible";
          }
        }
        return status;
      }
      
      const categories = ["Home Loan", "Personal Loan", "Vehicle Loan", "Education Loan"];
      const changesContainer = document.getElementById("simResultChanges");
      changesContainer.innerHTML = "";
      
      let changedCount = 0;
      categories.forEach(cat => {
        const origStatus = getEligibilityStatus(window.originalEligibility, cat);
        const simStatus = getEligibilityStatus(payload.eligibility, cat);
        if (origStatus.toUpperCase() !== simStatus.toUpperCase()) {
          const li = document.createElement("li");
          li.innerHTML = `<strong>${cat}</strong>: ${origStatus.toUpperCase()} &rarr; ${simStatus.toUpperCase()}`;
          changesContainer.appendChild(li);
          changedCount++;
        }
      });
      
      if (changedCount === 0) {
        const li = document.createElement("li");
        li.style.fontStyle = "italic";
        li.innerText = "No category statuses changed.";
        changesContainer.appendChild(li);
      }
      
    } catch (err) {
      alert(`Simulation error: ${err.message}`);
    } finally {
      runBtn.innerHTML = `<i class="fa-solid fa-play"></i> Recalculate Scenario`;
    }
  };
  
  resetBtn.onclick = () => {
    // Hide simulated elements
    document.getElementById("simulatedLabel").style.display = "none";
    document.getElementById("simResultBox").style.display = "none";
    resetBtn.style.display = "none";
    
    // Restore original HTML eligibility badges
    populateEligibility(window.originalEligibility);
    
    // Restore original HTML recommendations
    populateRecommendations(window.originalRecommendations, window.originalComparisons, customerId);
    
    // Restore original charts
    if (window.originalComparisons && window.originalComparisons.length > 0) {
      renderCharts(window.originalComparisons);
    }
  };
}

// Loan Improvement Advisor Action Plan
async function loadImprovementPlan(customerId) {
  const container = document.getElementById("timelineContainer");
  
  try {
    const res = await fetch(`${BASE_URL}/api/recommendations/improve/${customerId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);
    
    container.innerHTML = '';
    const timeline = data.timeline || [];
    
    if (timeline.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 20px; color: var(--text-muted); font-size: 12px;">
          All loans are fully approved. No profile improvements needed.
        </div>
      `;
      return;
    }
    
    timeline.forEach((step, idx) => {
      const item = document.createElement("div");
      item.className = "timeline-item";
      item.innerHTML = `
        <div class="timeline-marker">${idx + 1}</div>
        <div class="timeline-content">
          <h4>${step.title}</h4>
          <p>${step.action}</p>
          <span>Impact: ${step.impact}</span>
        </div>
      `;
      container.appendChild(item);
    });
  } catch (error) {
    console.error("Timeline advisor failed:", error);
    container.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-secondary); font-size: 12px;">
        Unavailable for this profile.
      </div>
    `;
  }
}

// Global Session History loader
async function loadHistorySessions() {
  const container = document.getElementById("historyListContainer");
  if (!container) return;
  
  try {
    const res = await fetch(`${BASE_URL}/api/history`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);
    
    const sessions = data.sessions || [];
    if (sessions.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 20px; color: var(--text-muted); font-size: 12px;">
          No previous sessions found.
        </div>
      `;
      return;
    }
    
    container.innerHTML = '';
    sessions.forEach(sess => {
      const item = document.createElement("div");
      item.className = "history-item";
      
      const date = new Date(sess.created_at + 'Z');
      const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      
      item.innerHTML = `
        <div class="history-info">
          <h4>${sess.name}</h4>
          <p>${sess.loan_purpose} Loan | Desired: ₹${Math.round(sess.desired_amount).toLocaleString()}</p>
          <small style="font-size: 9px; color: var(--text-muted);">${dateStr}</small>
        </div>
        <button class="history-action-btn">Load</button>
      `;
      
      item.querySelector("button").onclick = (e) => {
        e.stopPropagation();
        localStorage.setItem("currentCustomerId", sess.id);
        window.location.reload();
      };
      
      item.onclick = () => {
        localStorage.setItem("currentCustomerId", sess.id);
        window.location.reload();
      };
      
      container.appendChild(item);
    });
  } catch (error) {
    console.error("History list failed:", error);
  }
}
