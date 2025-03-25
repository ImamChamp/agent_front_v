import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from jira_ap import create_jira_issue, get_page_content, extract_page_id, fetch_confluence_context
from atlassian import Confluence
from jira import JIRA

import json
import uuid
import httpx
import requests

from mcp.server.fastmcp import FastMCP
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# GigaChat and LangChain imports
from langchain_community.chat_models.gigachat import GigaChat
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# LangGraph imports
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph

#прогнозирование отпусков сотрудников с помощью ML, не используя инструменты Marcdown, разбей минимум на 5 задач, по каждой задаче на отдельной строке жду описание, тип и название задачи

prompt_for_decompose = '''
Ты эксперт по декомпозиции сложных задач в методологии Agile. Твоя задача - разбивать комплексные требования в виде {task} на атомарные пользовательские истории (user stories), оценивать их сложность в story points и предлагать оптимальные сроки выполнения.
В первую очередь проанализируй запрос от пользователя, если он не указал планируемую дату завершения задачи ОБЯЗАТЕЛЬНО задай вопрос про это.
Во-вторых, ты должен знать количество сотрудников, которые будут работать над этой задачей и их роли в команде, если пользователь не указал их, то ОБЯЗАТЕЛЬНО уточни этот момент
не используя инструменты Marcdown, разбей минимум на 5 задач, по каждой задаче на отдельной строке жду описание, тип и название задачи'''
CONFLUENCE_URL = "https://queerxdisasster.atlassian.net/wiki"
CONFLUENCE_USERNAME = "7germania7@gmail.com"
CONFLUENCE_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

JIRA_SERVER = "https://queerxdisasster.atlassian.net"
JIRA_EMAIL = "7germania7@gmail.com"
JIRA_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

# Инициализация клиента Confluence
confluence = Confluence(
    url=CONFLUENCE_URL,
    username=CONFLUENCE_USERNAME,
    password=CONFLUENCE_API_TOKEN
)

# Инициализация клиента Jira
jira_options = {'server': JIRA_SERVER}
jira_client = JIRA(options=jira_options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))


app = Server("test")

# Create FastMCP instance
mcp = FastMCP(
    "gigachat",
    dependencies=[
        "langchain-community",
        "langchain-core",
        "langgraph",
        'jira'
    ],
)

# Directory for storing conversation history
PROFILE_DIR = (
        Path.home() / ".fastmcp" / os.environ.get("USER", "anon") / "gigachat"
).resolve()
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Initialize GigaChat model
model = GigaChat(
    credentials='NDk1MzkxZDYtYjQyYy00NjRiLTlkOWItZGY4MGY3MWY1MTg2Ojc5ZTllNWNlLWFmY2QtNDgwOC1iZjIxLWMwYmUyZjk0YWFmZA==',
    scope="GIGACHAT_API_PERS",
    model="GigaChat",
    verify_ssl_certs=False,
)

# Configure LangChain
parser = StrOutputParser()

# Configure LangGraph
# Initialize graph
workflow = StateGraph(state_schema=MessagesState)

# msg = requests.get(url)
# msg = msg.json()

# Define function that calls the model
def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": response}


original_dumps = json.dumps


def patched_dumps(*args, **kwargs):
    kwargs['ensure_ascii'] = False
    return original_dumps(*args, **kwargs)


json.dumps = patched_dumps


# Set graph vertex
workflow.add_edge(START, "model")
workflow.add_node("model", call_model)

# Add memory
memory = MemorySaver()
graph_app = workflow.compile(checkpointer=memory)
config = {"configurable": {"thread_id": "abc123"}}

# Store conversation sessions
conversation_history = {}

@mcp.tool()
async def confa(
    requirements_url: str,
):
    conf_result = ''
    message_list = requirements_url.split(' ')
    urls = [word.rstrip(',') for word in message_list if 'http' in word]
    for i in urls:
        requirements_content = fetch_confluence_context(confluence, requirements_url)
        conf_result += str(requirements_content) + '\n'
    # print("\nТребования из Confluence:")
    return conf_result


def model_out(session_id, system_message, message):
    if session_id not in conversation_history:
        conversation_history[session_id] = []

        # Add system message if provided
        if system_message:
            conversation_history[session_id].append(
                SystemMessage(content=system_message)
            )

    # Add user message to history
    conversation_history[session_id].append(HumanMessage(content=message))

    try:
        # Use LangGraph for processing
        input_messages = conversation_history[session_id]
        config = {"configurable": {"thread_id": session_id}}
        # Invoke the graph
        output = graph_app.invoke({"messages": input_messages}, config)
        # output = json.loads(output, ensure_ascii=False)
        # Get the response from the model
        ai_response = output["messages"][-1].content

        # Update conversation history
        conversation_history[session_id] = output["messages"]

        return ChatResponse(message=ai_response)
    except Exception as e:
        return ChatResponse(message=f"Error processing request: {str(e)}")


@dataclass
class ChatResponse:
    message: str
    timestamp: float = datetime.now(timezone.utc).timestamp()

@mcp.tool()
async def send_urls(
        message: str,
):
    message_list = message.split(' ')
    urls = [word for word in message_list if 'http' in word]
    return json.dumps(urls, indent=2)


@mcp.tool()
async def send_user_story(story, issue_type):
    story_name, story_description = story.split(': ')

    story_dict = {'project': 'const',
                  'summary': {story_name: story_description},
                  'description': 'const',
                  'issue_type': {'name': issue_type}}
    return story_dict


@mcp.tool()
async def chat(
        message: str,
        session_id: Optional[str] = 'default',
        system_message: Optional[str] = None,
) -> ChatResponse:
    """
    Send a message to GigaChat and get a response

    Args:
        message: The message to send to GigaChat
        session_id: Optional identifier for maintaining conversation history
        system_message: Optional system message to override the default

    Returns:
        ChatResponse object containing the AI's response
    """

    system_message = prompt_for_decompose
    # Initialize session if it doesn't exist
    if session_id not in conversation_history:
        conversation_history[session_id] = []

        # Add system message if provided
        if system_message:
            conversation_history[session_id].append(
                SystemMessage(content=system_message)
            )

    # Add user message to history
    conversation_history[session_id].append(HumanMessage(content=message))

    try:
        # Use LangGraph for processing
        input_messages = conversation_history[session_id]
        config = {"configurable": {"thread_id": session_id}}
        # Invoke the graph
        output = graph_app.invoke({"messages": input_messages}, config)
        ai_response = output["messages"][-1].content
        conversation_history[session_id] = output["messages"]

        return ChatResponse(message=ai_response)
    except Exception as e:
        return ChatResponse(message=f"Error processing request: {str(e)}")


@mcp.tool()
async def decompose(
        task: str,
        session_id: Optional[str] = None,
        # role: Optional[str] = None,
        # date: Optional[str] = None,
) -> ChatResponse:
    """
    Декомпозирование сложных задач на атомарные юзер-стори.

    Args:
        task: Задача, которую нужно декомпозировать.
        # role: The target language (default: "английский")
        # date: date of end
        session_id: your session_id

    Returns:
        Декомпозирование
    """



    urls_result = await confa(task)
    print(urls_result)
    config = {"configurable": {"thread_id": session_id}}
    # if (role or date) is None:
    #     return ChatResponse(message="Укажите, пожалуйста вашу роль и планируемую дату завершения задачи")

    try:

        if session_id not in conversation_history:
            conversation_history[session_id] = []

            # Add system message if provided
            if prompt_for_decompose:
                conversation_history[session_id].append(
                    SystemMessage(content=prompt_for_decompose)
                )

        # Add user message to history
        conversation_history[session_id].append(HumanMessage(content=task))

        try:
            # Use LangGraph for processing
            input_messages = conversation_history[session_id]
            config = {"configurable": {"thread_id": session_id}}
            # Invoke the graph
            output = graph_app.invoke({"messages": input_messages}, config)
            ai_response = output["messages"][-1].content
            conversation_history[session_id] = output["messages"]
        except Exception as e:
            print(e)

        # Create a translation-specific prompt template
        #
        # translation_prompt = ChatPromptTemplate.from_messages(
        #     [("system", translation_template), (
        #         "user", "Задача: {task}")]
        # )
        # translation_chain = translation_prompt | model | parser
        #
        # # Execute the translation
        # result = translation_chain.invoke({"task": task}, config)

        response = ChatResponse(message=ai_response)

        list_of_lines = response.message.split('\n')
        tsk_names = [wrd.lstrip("- **Название задачи**: ") for wrd in list_of_lines if 'Название' in wrd]
        tsk_types = [wrd.lstrip("- **Тип задачи**: ") for wrd in list_of_lines if 'Тип' in wrd]
        tsk_desc = [wrd.lstrip("- **Описание задачи**: ") for wrd in list_of_lines if 'Описание' in wrd]
        user_stories = []
        for i in range(len(tsk_names) - 1):
            if 'Task' in tsk_types[i]:
                tsl = 'Task'
            else:
                tsl = 'Epic'
            print(tsl)
            jira_dict = {
                'project': {'key': 'KAN'},  # ключ проекта в Jira
                'summary': tsk_names[i],
                'description': tsk_desc[i],
                'issuetype': {'name': tsl},
            }
            user_stories.append(jira_dict)
        # for us in user_stories:
        #     issue_key = create_jira_issue(jira_client, us)
        #     print(f"Создана задача: {issue_key}")
        return ChatResponse(message=ai_response)
    except Exception as e:
        return ChatResponse(message=f"Translation error: {str(e)}")


@mcp.tool()
async def clear_history(
        session_id: str = "default",
) -> str:
    """
    Clear the conversation history for a specific session

    Args:
        session_id: The session ID to clear (default: "default")

    Returns:
        Confirmation message
    """
    if session_id in conversation_history:
        conversation_history[session_id] = []
        return f"Conversation history for session {session_id} cleared."
    else:
        return f"No conversation history found for session {session_id}."


@mcp.tool()
async def list_sessions() -> List[str]:
    """
    List all active conversation sessions

    Returns:
        List of session IDs
    """
    return list(conversation_history.keys())


@mcp.tool()
async def get_history(
        session_id: str = "default",
        max_messages: int = 10,
) -> List[dict]:
    """
    Get the conversation history for a specific session

    Args:
        session_id: The session ID to retrieve (default: "default")
        max_messages: Maximum number of messages to return (default: 10)

    Returns:
        List of message dictionaries with role and content
    """
    if session_id not in conversation_history:
        return []

    history = conversation_history[session_id]

    # Convert to simple dictionaries for the last max_messages
    formatted_history = []
    for msg in history[-max_messages:]:
        if isinstance(msg, HumanMessage):
            formatted_history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            formatted_history.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, SystemMessage):
            formatted_history.append({"role": "system", "content": msg.content})

    return formatted_history


if __name__ == "__main__":
    # Simple test of the chat functionality
    async def new_message():
        pass

    async def test():
        tsk = input("Enter your task: ")
        ss_id = input("Enter your session_id: ")
        while 'Выход' not in tsk:
            response = await decompose(tsk, ss_id)
            print(f"Response: {response.message}")
            tsk = input("Enter your message: ")
        # translation = await translate("Привет, как дела?", "английский")
        # print(f"Translation: {translation.message}")


    asyncio.run(test())