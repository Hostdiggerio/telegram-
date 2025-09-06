import os
import requests
import time
import base64
import json
from mistralai import Mistral
from mistralai.models import File
import logging
from typing import List, Union, Optional, Dict, Any
# Load environment variables from .env file (if available)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, skip loading .env file
    pass

# It's recommended to set your API key as an environment variable
# For example: export MISTRAL_API_KEY='your_api_key'
api_key = os.environ.get("MISTRAL_API_KEY")

if not api_key:
    raise ValueError("MISTRAL_API_KEY environment variable not set. Please create a .env file or set the environment variable.")

client = Mistral(api_key=api_key)
logger = logging.getLogger(__name__)

# Add these agent creation functions after the client initialization
def create_websearch_agent():
    """Create a web search agent"""
    try:
        return client.beta.agents.create(
            model="mistral-medium-2505",
            description="Agent able to search information over the web, such as news, weather, sport results...",
            name="Websearch Agent",
            instructions="You have the ability to perform web searches with `web_search` to find up-to-date information.",
            tools=[{"type": "web_search"}],
            completion_args={
                "temperature": 0.3,
                "top_p": 0.95,
            }
        )
    except Exception as e:
        logger.error(f"Failed to create web search agent: {e}")
        raise

def create_code_agent():
    """Create a code interpreter agent"""
    try:
        return client.beta.agents.create(
            model="mistral-medium-2505",
            name="Coding Agent",
            description="Agent used to execute code using the interpreter tool.",
            instructions="Use the code interpreter tool when you have to run code.",
            tools=[{"type": "code_interpreter"}],
            completion_args={
                "temperature": 0.3,
                "top_p": 0.95,
            }
        )
    except Exception as e:
        logger.error(f"Failed to create code interpreter agent: {e}")
        raise

def create_image_agent():
    """Create an image generation agent"""
    try:
        return client.beta.agents.create(
            model="mistral-medium-2505",
            name="Image Generation Agent",
            description="Agent used to generate images.",
            instructions="Use the image generation tool when you have to create images.",
            tools=[{"type": "image_generation"}],
            completion_args={
                "temperature": 0.3,
                "top_p": 0.95,
            }
        )
    except Exception as e:
        logger.error(f"Failed to create image generation agent: {e}")
        raise

# Add library management functions
def create_library(name: str, description: str = ""):
    """Create a new document library"""
    try:
        return client.beta.libraries.create(name=name, description=description)
    except Exception as e:
        logger.error(f"Failed to create library '{name}': {e}")
        raise

def list_libraries():
    """List all available libraries"""
    try:
        return client.beta.libraries.list().data
    except Exception as e:
        logger.error(f"Failed to list libraries: {e}")
        raise

def upload_document_to_library(library_id: str, file_path: str, file_name: Optional[str] = None):
    """Upload a document to a library"""
    if file_name is None:
        file_name = os.path.basename(file_path)
    
    try:
        with open(file_path, "rb") as file_content:
            return client.beta.libraries.documents.upload(
                library_id=library_id,
                file=File(file_name=file_name, content=file_content.read()),
            )
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Failed to upload document '{file_name}' to library {library_id}: {e}")
        raise

def create_document_library_agent(library_ids: List[str]):
    """Create an agent with access to document libraries"""
    try:
        return client.beta.agents.create(
            model="mistral-medium-2505",
            name="Document Library Agent",
            description="Agent used to access documents from the document library.",
            instructions="Use the library tool to access external documents.",
            tools=[{"type": "document_library", "library_ids": library_ids}],
            completion_args={
                "temperature": 0.3,
                "top_p": 0.95,
            }
        )
    except Exception as e:
        logger.error(f"Failed to create document library agent: {e}")
        raise

def query_document_library(agent_id: str, query: str):
    """Query a document library using an agent"""
    try:
        return client.beta.conversations.start(
            agent_id=agent_id,
            inputs=[{"role": "user", "content": query}]
        )
    except Exception as e:
        logger.error(f"Failed to query document library: {e}")
        raise

# Additional agent management functions
def list_agents():
    """List all available agents"""
    try:
        # Make API call with try/except for safety
        try:
            response = client.beta.agents.list()  # type: ignore
        except AttributeError:
            logger.warning("agents.list() method not available")
            return []
        
        # Handle different response types safely
        if hasattr(response, 'data'):
            return response.data  # type: ignore
        elif isinstance(response, list):
            return response
        else:
            return []
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        return []

def get_agent_by_id(agent_id: str):
    """Get a specific agent by ID"""
    try:
        # Try different API methods safely
        try:
            if hasattr(client.beta.agents, 'get'):
                return client.beta.agents.get(agent_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        try:
            if hasattr(client.beta.agents, 'retrieve'):
                return client.beta.agents.retrieve(agent_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        # Fallback: get from list
        agents = list_agents()
        for agent in agents:
            if getattr(agent, 'id', None) == agent_id:
                return agent
        return None
    except Exception as e:
        logger.error(f"Failed to get agent {agent_id}: {e}")
        return None

def delete_agent(agent_id: str):
    """Delete an agent"""
    try:
        # Try different API methods safely
        try:
            if hasattr(client.beta.agents, 'delete'):
                return client.beta.agents.delete(agent_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        try:
            if hasattr(client.beta.agents, 'remove'):
                return client.beta.agents.remove(agent_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        logger.warning(f"Agent deletion not supported by current API version")
        raise NotImplementedError("Agent deletion not supported")
    except NotImplementedError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete agent {agent_id}: {e}")
        raise

def delete_library(library_id: str):
    """Delete a library"""
    try:
        # Try different API methods safely
        try:
            if hasattr(client.beta.libraries, 'delete'):
                return client.beta.libraries.delete(library_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        try:
            if hasattr(client.beta.libraries, 'remove'):
                return client.beta.libraries.remove(library_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        logger.warning(f"Library deletion not supported by current API version")
        raise NotImplementedError("Library deletion not supported")
    except NotImplementedError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete library {library_id}: {e}")
        raise

def list_library_documents(library_id: str):
    """List documents in a library"""
    try:
        # Try different API call patterns safely
        response = None
        
        try:
            if hasattr(client.beta.libraries, 'documents'):
                response = client.beta.libraries.documents.list(library_id)  # type: ignore
        except (AttributeError, TypeError):
            pass
        
        if response is None:
            try:
                if hasattr(client.beta.libraries, 'list_documents'):
                    response = client.beta.libraries.list_documents(library_id)  # type: ignore
            except (AttributeError, TypeError):
                pass
        
        # Handle different response types
        if response is None:
            return []
        elif hasattr(response, 'data'):
            return response.data  # type: ignore
        elif isinstance(response, list):
            return response
        else:
            return []
    except Exception as e:
        logger.error(f"Failed to list documents in library {library_id}: {e}")
        return []

# Global agent cache to reuse agents
_agent_cache = {}

def get_or_create_agent_for_tool(tool: str):
    """Get or create an agent for a specific built-in tool"""
    if tool in _agent_cache:
        return _agent_cache[tool]
    
    try:
        if tool == "web_search":
            agent = create_websearch_agent()
        elif tool == "code_interpreter": 
            agent = create_code_agent()
        else:
            logger.error(f"Unknown built-in tool: {tool}")
            return None
        
        _agent_cache[tool] = agent
        logger.info(f"Created and cached agent for {tool}: {getattr(agent, 'id', 'unknown')}")
        return agent
    except Exception as e:
        logger.error(f"Failed to create agent for {tool}: {e}")
        return None

def handle_builtin_tools_with_agents(prompt: str, history: List[dict], tools: List[str], 
                                   system_prompt: Optional[str], model: str, temperature: float, 
                                   top_p: float, max_tokens: int) -> Union[str, None]:
    """Handle built-in tools using the agent-based approach"""
    try:
        # For multiple tools, prioritize web_search, then code_interpreter
        primary_tool = None
        if "web_search" in tools:
            primary_tool = "web_search"
        elif "code_interpreter" in tools:
            primary_tool = "code_interpreter"
        
        if not primary_tool:
            logger.error("No supported built-in tools found")
            return "I'm sorry, I couldn't process that request with the available tools."
        
        # Get or create the appropriate agent
        agent = get_or_create_agent_for_tool(primary_tool)
        if not agent:
            return "I'm sorry, I couldn't set up the required tools to help you."
        
        # Prepare conversation inputs
        inputs = []
        if system_prompt:
            inputs.append({"role": "system", "content": system_prompt})
        
        # Add history
        for msg in history:
            inputs.append({"role": msg["role"], "content": msg["content"]})
        
        # Add current prompt
        inputs.append({"role": "user", "content": prompt})
        
        # Start conversation with agent
        agent_id = getattr(agent, 'id', None)
        if not agent_id:
            logger.error("Agent does not have an ID")
            return "I'm sorry, there was an issue with the agent setup."
        
        response = client.beta.conversations.start(
            agent_id=agent_id,
            inputs=inputs
        )
        
        # Extract response text
        if hasattr(response, 'outputs') and response.outputs:
            for output in response.outputs:
                if hasattr(output, 'type') and getattr(output, 'type', '') == "message.output":
                    output_content = getattr(output, 'content', None)
                    if output_content:
                        content_list = output_content if isinstance(output_content, list) else [output_content]
                        for content in content_list:
                            content_text = None
                            if hasattr(content, 'text'):
                                content_text = getattr(content, 'text', None)
                            elif isinstance(content, str):
                                content_text = content
                            
                            if content_text:
                                return content_text
        
        return "I processed your request but didn't get a clear response."
        
    except Exception as e:
        logger.error(f"Agent-based tool handling failed: {e}")
        return "I'm sorry, I encountered an error while processing your request."

ToolType = Union[str, dict]

def send_prompt(prompt: str, history: List[dict] = [], tools: List[ToolType] = [], model: str = "mistral-large-latest",
                temperature: float = 0.7, top_p: float = 1.0, system_prompt: Optional[str] = None, max_tokens: int = 4096) -> Union[str, dict, None]:
    """
    Sends a prompt to the Mistral API using the official client.
    Handles both regular chat, image generation, and custom functions using Mistral's native tools.
    """
    
    # Check if this is an image generation request - use Mistral's conversations API
    if "image_generation" in tools:
        return generate_image_with_mistral(prompt, history, system_prompt, model, temperature, top_p, max_tokens)
    
    # Check if we have built-in tools that need agent-based approach
    builtin_tools = [t for t in tools if isinstance(t, str) and t in ["web_search", "code_interpreter"]]
    if builtin_tools and not any(isinstance(t, dict) and t.get("type") == "function" for t in tools):
        # Use agent-based approach for built-in tools
        return handle_builtin_tools_with_agents(prompt, history, builtin_tools, system_prompt, model, temperature, top_p, max_tokens)
    
    # Handle regular chat completion with potential custom functions
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": prompt})

    try:
        # Handle function/tool calling for custom functions and built-in tools
        processed_tools = []
        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "function":
                # Custom function tool - already in correct format
                processed_tools.append(tool)
            elif isinstance(tool, str) and tool not in ["image_generation"]:
                # Built-in tools - format correctly for current Mistral API
                if tool in ["web_search", "code_interpreter"]:
                    processed_tools.append({"type": tool})
                else:
                    # Other built-in tools, handle as string
                    processed_tools.append({"type": tool})
        
        chat_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        
        # Add tools if any are present
        if processed_tools:
            chat_kwargs["tools"] = processed_tools
        
        chat_response = client.chat.complete(**chat_kwargs)
        
        # Check if the response contains tool calls
        if hasattr(chat_response.choices[0].message, 'tool_calls') and chat_response.choices[0].message.tool_calls:
            tool_calls = []
            for tool_call in chat_response.choices[0].message.tool_calls:
                tool_calls.append({
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })
            return {"type": "tool_calls", "content": tool_calls}
        
        content = chat_response.choices[0].message.content
        return str(content) if content is not None else None

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return None

def generate_image_with_mistral(prompt: str, history: List[dict] = [], system_prompt: Optional[str] = None, 
                               model: str = "mistral-large-latest", temperature: float = 0.7, 
                               top_p: float = 1.0, max_tokens: int = 4096) -> Union[str, None]:
    """
    Generates an image using Mistral's native image generation tool via the conversations API.
    """
    try:
        logger.info(f"Generating image with Mistral's native API. Prompt: '{prompt}'")
        
        # Prepare the conversation inputs
        inputs = []
        
        # Add system message if provided
        if system_prompt:
            inputs.append({"role": "system", "content": system_prompt})
        
        # Add history
        for msg in history:
            inputs.append({"role": msg["role"], "content": msg["content"]})
        
        # Add current prompt
        inputs.append({"role": "user", "content": prompt})
        
        # Prepare the payload for conversations API
        # Use a model that's known to work well with image generation
        image_model = "mistral-large-latest"  # Use large model for better image generation
        
        payload = {
            "model": image_model,
            "inputs": inputs,
            "tools": [{"type": "image_generation"}],
            "completion_args": {
                "temperature": 0.7,
                "max_tokens": 2048,
                "top_p": 1
            },
            "stream": False,  # Set to False to get complete JSON response
            "instructions": ""
        }
        
        # Make direct API call to conversations endpoint
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key
        }
        
        # Add retry logic for better reliability
        response = None
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.mistral.ai/v1/conversations",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                
                # If successful, break out of retry loop
                if response.status_code == 200:
                    break
                elif response.status_code == 500 and attempt < max_retries - 1:
                    # Retry on 500 errors
                    logger.warning(f"Attempt {attempt + 1} failed with 500 error, retrying...")
                    time.sleep(2)  # Wait 2 seconds before retry
                    continue
                    
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                    time.sleep(2)
                    continue
                else:
                    logger.error("Request timed out after all retries")
                    return None
            except Exception as e:
                logger.error(f"Request failed on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(2)
                continue
        
        if response is None:
            logger.error("Failed to get response after all retry attempts")
            return None
            
        if response.status_code == 200:
            try:
                response_data = response.json()
                logger.info(f"Mistral image generation response received")
                logger.debug(f"Response data: {response_data}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                logger.error(f"Response content: {response.text}")
                logger.error(f"Response headers: {response.headers}")
                return None
            
            # Parse the response to extract image data from Mistral's conversations API
            if "outputs" in response_data:
                for output in response_data["outputs"]:
                    # Check for message output with tool_file content
                    if (output.get("type") == "message.output" and 
                        "content" in output and 
                        isinstance(output["content"], list)):
                        
                        for content_item in output["content"]:
                            if (isinstance(content_item, dict) and 
                                content_item.get("type") == "tool_file" and 
                                content_item.get("tool") == "image_generation"):
                                
                                file_id = content_item.get("file_id")
                                if file_id:
                                    logger.info(f"Found image file_id: {file_id}")
                                    return download_image_by_id(file_id)
                    
                    # Also check for direct content with image data
                    elif "content" in output:
                        content = output["content"]
                        if isinstance(content, dict) and "image" in content:
                            return handle_mistral_image_response(content["image"])
                        elif isinstance(content, str) and ("http" in content or "data:image" in content):
                            return handle_mistral_image_response(content)
            
            # Fallback checks for other possible response formats
            if "image_url" in response_data:
                return handle_mistral_image_response(response_data["image_url"])
            
            if "file_id" in response_data:
                return download_image_by_id(response_data["file_id"])
            
            # If we get here, the response format wasn't what we expected
            logger.warning(f"Unexpected response format from Mistral image generation: {response_data}")
            return None
            
        else:
            logger.error(f"Mistral image generation failed. Status: {response.status_code}, Response: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Mistral image generation failed: {e}", exc_info=True)
        return None

def parse_streaming_response(response_text: str) -> dict:
    """
    Parse the streaming response from Mistral API to extract JSON data.
    """
    try:
        lines = response_text.strip().split('\n')
        for line in lines:
            if line.startswith('data: '):
                json_str = line[6:]  # Remove 'data: ' prefix
                if json_str and json_str != '[DONE]':
                    return json.loads(json_str)
        return {}
    except Exception as e:
        logger.error(f"Failed to parse streaming response: {e}")
        return {}

def handle_mistral_image_response(image_data: Union[str, dict]) -> Union[str, None]:
    """
    Handles the image response from Mistral API, downloading or decoding as needed.
    """
    try:
        if isinstance(image_data, str):
            if image_data.startswith("http"):
                # It's a URL, download the image
                response = requests.get(image_data, timeout=30)
                if response.status_code == 200:
                    filename = f"temp_image_{int(time.time())}.png"
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Downloaded image from Mistral: {filename}")
                    return filename
            elif image_data.startswith("data:image"):
                # It's base64 encoded image data
                header, encoded = image_data.split(',', 1)
                image_bytes = base64.b64decode(encoded)
                filename = f"temp_image_{int(time.time())}.png"
                with open(filename, 'wb') as f:
                    f.write(image_bytes)
                logger.info(f"Decoded base64 image from Mistral: {filename}")
                return filename
        
        logger.error(f"Unhandled image data format: {type(image_data)}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to handle Mistral image response: {e}")
        return None

def download_image_by_id(file_id: str) -> Union[str, None]:
    """
    Downloads an image using Mistral's file ID (similar to old browser-based approach).
    """
    try:
        # Try to use the files API to download
        headers = {
            "X-API-KEY": api_key
        }
        
        # First, try to get the file URL
        response = requests.get(
            f"https://api.mistral.ai/v1/files/{file_id}/url",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            signed_url = response.json().get('url')
            if signed_url:
                # Download the actual image
                image_response = requests.get(signed_url, timeout=30)
                if image_response.status_code == 200:
                    filename = f"temp_image_{int(time.time())}.png"
                    with open(filename, 'wb') as f:
                        f.write(image_response.content)
                    logger.info(f"Downloaded image via file ID: {filename}")
                    return filename
        
        logger.error(f"Failed to download image with file ID: {file_id}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to download image by ID: {e}")
        return None

def transcribe_audio(audio_file_path: str, model: str = "voxtral-mini-latest") -> str:
    """
    Transcribes an audio file using the Mistral API.
    """
    try:
        with open(audio_file_path, "rb") as f:
            # Create a File object for the audio
            audio_file = File(
                file_name="audio.mp3",
                content=f.read(),
                content_type="audio/mpeg"
            )
            
            transcription_response = client.audio.transcriptions.complete(
                model=model,
                file=audio_file,
            )
        return transcription_response.text or ""
    except Exception as e:
        logger.error(f"An error occurred during audio transcription: {e}", exc_info=True)
        return ""