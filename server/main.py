from typing import TypedDict, Annotated, Optional
from langgraph.graph import add_messages, StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessageChunk, ToolMessage
from dotenv import load_dotenv
from langchain_tavily import TavilySearch


# from langchain_community.tools.tavily_search import TavilySearchResults
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
from uuid import uuid4
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()

# Initialize memory saver for checkpointing
memory = MemorySaver()

class State(TypedDict):
    messages: Annotated[list, add_messages]

search_tool = TavilySearch(
    max_results=4,
)

tools = [search_tool]

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-001') # initialize the class
# llm = ChatOpenAI(model="gpt-4o")

llm_with_tools = llm.bind_tools(tools=tools)

async def model(state: State):
    result = await llm_with_tools.ainvoke(state["messages"])
    return {
        "messages": [result], 
    }

async def tools_router(state: State):
    last_message = state["messages"][-1]

    if(hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0):
        return "tool_node"
    else: 
        return END
    
async def tool_node(state):
    """Custom tool node that handles tool calls from the LLM."""
    # Get the tool calls from the last message
    tool_calls = state["messages"][-1].tool_calls
    
    # Initialize list to store tool messages
    tool_messages = []
    
    # Process each tool call
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]
        
        # Handle the search tool
        if tool_name == "tavily_search_results_json":
            # Execute the search tool with the provided arguments
            search_results = await search_tool.ainvoke(tool_args)
            
            # Create a ToolMessage for this result
            tool_message = ToolMessage(
                content=str(search_results),
                tool_call_id=tool_id,
                name=tool_name
            )
            
            tool_messages.append(tool_message)
    
    # Add the tool messages to the state
    return {"messages": tool_messages}

graph_builder = StateGraph(State)

graph_builder.add_node("model", model)
graph_builder.add_node("tool_node", tool_node)
graph_builder.set_entry_point("model")

graph_builder.add_conditional_edges("model", tools_router)
graph_builder.add_edge("tool_node", "model")

graph = graph_builder.compile(checkpointer=memory)

app = FastAPI() # initialized the fast api app

# Add CORS middleware with settings that match frontend requirements
# browser/client to comunicate w server endpoint
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"], 
    expose_headers=["Content-Type"], 
)

def serialise_ai_message_chunk(chunk): 
    # method will check whether this chunk is an instance of AI Message chunk
    if(isinstance(chunk, AIMessageChunk)):
        return chunk.content
    else: # if error
        raise TypeError(
            f"Object of type {type(chunk).__name__} is not correctly formatted for serialisation"
        )

async def generate_chat_responses(message: str, checkpoint_id: Optional[str] = None):
    is_new_conversation = checkpoint_id is None # checking checkpoint id
    
    if is_new_conversation:
        # Generate new checkpoint ID for first message in conversation
        new_checkpoint_id = str(uuid4())

        config = { # constructing the config object
            "configurable": {
                "thread_id": new_checkpoint_id
            }
        }
        
        # Initialize with first message
        events = graph.astream_events(
            {"messages": [HumanMessage(content=message)]},
            version="v2",
            config=config
        )
        
        # First send the checkpoint ID
        # yeild or emit the events
        # \ to escape ""
        yield f"data: {{\"type\": \"checkpoint\", \"checkpoint_id\": \"{new_checkpoint_id}\"}}\n\n" # thats how browser will know that its a sse
    else: # existing conversation
        config = {
            "configurable": {
                "thread_id": checkpoint_id
            }
        }
        # Continue existing conversation
        events = graph.astream_events(
            {"messages": [HumanMessage(content=message)]},
            version="v2",
            config=config
        )

    async for event in events:
        event_type = event["event"]
        # so client can differentiate between each event type        
        if event_type == "on_chat_model_stream":
            # grabbing message chunk and passing inside method
            
            chunk_content = serialise_ai_message_chunk(event["data"]["chunk"])

            # Escape single quotes and newlines manually for safe JSON parsing
            # safe_content = chunk_content.replace("'", "\\'").replace("\n", "\\n")
            
            safe_content = json.dumps(chunk_content)
            #yielding this data/json to client
            # yield f"data: {{\"type\": \"content\", \"content\": \"{safe_content}\"}}\n\n" # sse protocol
            yield f"data: {json.dumps({'type': 'content', 'content': chunk_content})}\n\n"

            # content=empty on tool call
        elif event_type == "on_chat_model_end":
            # Check if there are tool calls for search
            tool_calls = event["data"]["output"].tool_calls if hasattr(event["data"]["output"], "tool_calls") else []
            search_calls = [call for call in tool_calls if call["name"] == "tavily_search_results_json"]
            
            if search_calls:
                # Signal that a search is starting
                search_query = search_calls[0]["args"].get("query", "")
                # Escape quotes and special characters
                # safe_query = search_query.replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n")

                safe_query = json.dumps(search_query)
                # yield f"data: {{\"type\": \"search_start\", \"query\": \"{safe_query}\"}}\n\n"
                yield f"data: {json.dumps({'type': 'search_start', 'query': search_query})}\n\n"


            # tool end will have all the info of tool                
        elif event_type == "on_tool_end" and event["name"] == "tavily_search_results_json":
            # Search completed - send results or error
            output = event["data"]["output"]
            
            # Check if output is a list 
            if isinstance(output, list): # o/p(response of tavily search) will be a list
                # Extract URLs from list of search results too show on UI
                urls = []
                for item in output:
                    if isinstance(item, dict) and "url" in item:
                        urls.append(item["url"])
                
                # Convert URLs to JSON and yield them
                urls_json = json.dumps(urls)
                # yield f"data: {{\"type\": \"search_results\", \"urls\": {urls_json}}}\n\n"
                yield f"data: {json.dumps({'type': 'search_results', 'urls': urls})}\n\n"

    
    # Send an end event
    yield f"data: {{\"type\": \"end\"}}\n\n"

@app.get("/chat_stream/{message}") # user entered message info will come here
# 2nd argument. = checkpoint id = provided as a query parameter
# default to none if client doesnt provide. a checkpoint id
async def chat_stream(message: str, checkpoint_id: Optional[str] = Query(None)):
    return StreamingResponse( # class of fastapi
        generate_chat_responses(message, checkpoint_id), # providing generator function 1st=will emit events anytime it receives something
        media_type="text/event-stream"
    )

@app.get("/")
def read_root():
    return {"message": "🚀 Perplexity chatbot backend is live"}

# SSE - server-sent events - unidirectional
# web sockets establish a consistent connection between the server and the client; overkill here
# uvicorn app:app --reload ; 2nd app will reference app fast api variable/instance
# reload = server restart automatically if we want to makeany changes``
# /Applications/Python\ 3.9/Install\ Certificates.command 