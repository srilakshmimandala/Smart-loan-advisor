import os
import time
import asyncio
import re
import litellm
from langchain_groq import ChatGroq
from utils.logger import get_logger

# Drop unsupported params (e.g. cache_breakpoint) for providers like Groq
litellm.drop_params = True

# Patch LiteLLM to strip cache_breakpoint from messages, which Groq doesn't support
original_completion = litellm.completion
original_acompletion = litellm.acompletion

logger = get_logger("LLMClient")

def clean_messages(messages):
    if not messages or not isinstance(messages, list):
        return messages
    cleaned = []
    for msg in messages:
        if isinstance(msg, dict):
            cleaned.append({k: v for k, v in msg.items() if k != "cache_breakpoint"})
        else:
            cleaned.append(msg)
    return cleaned

def patched_completion(*args, **kwargs):
    if "messages" in kwargs:
        kwargs["messages"] = clean_messages(kwargs["messages"])
    elif len(args) > 1 and isinstance(args[1], list):
        args = list(args)
        args[1] = clean_messages(args[1])
        
    max_retries = 5
    base_delay = 5
    for attempt in range(max_retries):
        try:
            return original_completion(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            is_too_large = (
                "request too large" in err_msg.lower() or 
                "please reduce your message size" in err_msg.lower() or
                "tpd" in err_msg.lower() or
                "tokens per day" in err_msg.lower() or
                "decommissioned" in err_msg.lower()
            )
            if is_too_large:
                current_model = kwargs.get("model") or (args[0] if len(args) > 0 else "")
                fallback_model = None
                if "llama3-8b-8192" in current_model:
                    fallback_model = current_model.replace("llama3-8b-8192", "llama-3.1-8b-instant")
                
                if fallback_model:
                    logger.warning(f"Rate limit / TPD / Size limit hit for {current_model}. Falling back to {fallback_model}...")
                    if "model" in kwargs:
                        kwargs["model"] = fallback_model
                    elif len(args) > 0:
                        args = list(args)
                        args[0] = fallback_model
                    continue
                raise e
            elif "rate_limit" in err_msg.lower() or "rate limit" in err_msg.lower() or "429" in err_msg:
                match = re.search(r"try again in (\d+(?:\.\d+)?)s", err_msg)
                if match:
                    wait_time = float(match.group(1)) + 1.5
                else:
                    wait_time = base_delay * (2 ** attempt)
                logger.warning(f"Rate limit hit. Retrying in {wait_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise e
    return original_completion(*args, **kwargs)

async def patched_acompletion(*args, **kwargs):
    if "messages" in kwargs:
        kwargs["messages"] = clean_messages(kwargs["messages"])
    elif len(args) > 1 and isinstance(args[1], list):
        args = list(args)
        args[1] = clean_messages(args[1])
        
    max_retries = 5
    base_delay = 5
    for attempt in range(max_retries):
        try:
            return await original_acompletion(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            is_too_large = (
                "request too large" in err_msg.lower() or 
                "please reduce your message size" in err_msg.lower() or
                "tpd" in err_msg.lower() or
                "tokens per day" in err_msg.lower() or
                "decommissioned" in err_msg.lower()
            )
            if is_too_large:
                current_model = kwargs.get("model") or (args[0] if len(args) > 0 else "")
                fallback_model = None
                if "llama3-8b-8192" in current_model:
                    fallback_model = current_model.replace("llama3-8b-8192", "llama-3.1-8b-instant")
                
                if fallback_model:
                    logger.warning(f"Rate limit / TPD / Size limit hit for {current_model}. Falling back to {fallback_model}...")
                    if "model" in kwargs:
                        kwargs["model"] = fallback_model
                    elif len(args) > 0:
                        args = list(args)
                        args[0] = fallback_model
                    continue
                raise e
            elif "rate_limit" in err_msg.lower() or "rate limit" in err_msg.lower() or "429" in err_msg:
                match = re.search(r"try again in (\d+(?:\.\d+)?)s", err_msg)
                if match:
                    wait_time = float(match.group(1)) + 1.5
                else:
                    wait_time = base_delay * (2 ** attempt)
                logger.warning(f"Rate limit hit in async call. Retrying in {wait_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                raise e
    return await original_acompletion(*args, **kwargs)

litellm.completion = patched_completion
litellm.acompletion = patched_acompletion

# Retrieve API key
api_key = os.getenv("GROQ_API_KEY")

if not api_key or api_key == "your_groq_api_key_here":
    logger.warning("GROQ_API_KEY is not set or contains the default placeholder. API calls will fail.")

def get_langchain_groq_model(model_name="llama3-8b-8192", temperature=0.2):
    """
    Returns a ChatGroq instance for use with LangChain and CrewAI.
    """
    try:
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError("GROQ_API_KEY is missing from environment.")
        return ChatGroq(
            model=model_name,
            groq_api_key=api_key,
            temperature=temperature
        )
    except Exception as e:
        logger.error(f"Failed to initialize ChatGroq model: {str(e)}")
        raise e

def get_crewai_llm():
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model="llama3-8b-8192",
        temperature=0.3
    )

class GroqRawWrapper:
    """
    A compatibility wrapper that mimics Google Gemini model response formats
    using the Groq API to avoid modifying call sites in other files.
    """
    def __init__(self, model_name):
        self.model_name = model_name
        from groq import Groq
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError("GROQ_API_KEY is missing from environment.")
        self.client = Groq(api_key=api_key)

    def generate_content(self, prompt: str):
        class GeminiLikeResponse:
            def __init__(self, text):
                self.text = text
        for attempt in range(3):
            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model_name,
                )
                return GeminiLikeResponse(chat_completion.choices[0].message.content)
            except Exception as e:
                err_msg = str(e)
                if "decommissioned" in err_msg.lower() and "llama3-8b-8192" in self.model_name:
                    logger.warning(f"Raw Groq model decommissioned. Falling back from {self.model_name} to llama-3.1-8b-instant...")
                    self.model_name = self.model_name.replace("llama3-8b-8192", "llama-3.1-8b-instant")
                    continue
                elif "rate_limit" in err_msg.lower() and attempt < 2:
                    time.sleep(30)
                else:
                    raise e

def get_raw_gemini_model(model_name="llama3-8b-8192"):
    """
    Compatibility wrapper returning a raw Groq executor mimicking Gemini interface.
    """
    return GroqRawWrapper(model_name)

def test_connection():
    """
    Tests the Groq connection by asking a simple question.
    """
    try:
        logger.info("Testing connection to Groq API...")
        model = get_raw_gemini_model()
        response = model.generate_content("What is a personal loan? Keep it under 20 words.")
        logger.info(f"Groq API Response: {response.text.strip()}")
        return True
    except Exception as e:
        logger.error(f"Groq API connection test failed: {str(e)}")
        return False

if __name__ == "__main__":
    test_connection()
