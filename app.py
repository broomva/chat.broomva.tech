from typing import Dict, Optional

import chainlit as cl
from chainlit.input_widget import Select, Slider, Switch
from langchain.chains import (ConversationalRetrievalChain,
                              RetrievalQAWithSourcesChain)
from langchain.memory import ChatMessageHistory, ConversationBufferMemory
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
embeddings = OpenAIEmbeddings()
vector_store = FAISS.load_local("docs.faiss", embeddings, allow_dangerous_deserialization=True)

# @cl.oauth_callback
# def oauth_callback(
#     provider_id: str,
#     token: str,
#     raw_user_data: Dict[str, str],
#     default_app_user: cl.User,
# ) -> Optional[cl.User]:
#     # set AppUser tags as regular_user
#     match default_app_user.username:
#         case "Broomva":
#             default_app_user.tags = ["admin_user"]
#             default_app_user.role = "admin"
#         case _:
#             default_app_user.tags = ["regular_user"]
#             default_app_user.role = "guest"
#     # print(default_app_user)
#     return default_app_user


@cl.password_auth_callback
def auth_callback(
    username: str = "guest", password: str = "guest"
) -> Optional[cl.User]:
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    import hashlib

    # Create a new sha256 hash object
    hash_object = hashlib.sha256()

    # Hash the password
    hash_object.update(password.encode())

    # Get the hexadecimal representation of the hash
    hashed_password = hash_object.hexdigest()

    if (username, hashed_password) == (
        "broomva",
        "b68cacbadaee450b8a8ce2dd44842f1de03ee9993ad97b5e99dea64ef93960ba",
    ):
        # return cl.User(username="Broomva", role="OWNER", provider="credentials", tags = ["admin_user"])
        return cl.User(
            identifier="broomva", metadata={"role": "admin", "provider": "credentials"}
        )
    elif (username, password) == ("guest", "guest"):
        return cl.User(
            identifier="guest", metadata={"role": "user", "provider": "credentials"}
        )
    else:
        return None


# @cl.set_chat_profiles
# async def chat_profile(current_user: cl.User):
#     if "admin" not in current_user.role:
#         # Default to 3.5 when not admin
#         return [
#             cl.ChatProfile(
#                 name="Broomva Book Agent",
#                 markdown_description="The underlying LLM model is **GPT-3.5**.",
#             ),
#         ]

#     return [
#         cl.ChatProfile(
#             name="Turbo Agent",
#             markdown_description="The underlying LLM model is **GPT-3.5**.",
#         ),
#         cl.ChatProfile(
#             name="GPT4 Agent",
#             markdown_description="The underlying LLM model is **GPT-4 Turbo**.",
#         ),
#     ]


@cl.on_settings_update
async def setup_agent(settings):
    print("on_settings_update", settings)
    get_chain()

def get_chain():
    settings = cl.user_session.get("settings")
    # chat_profile = cl.user_session.get("chat_profile")

    # if chat_profile == "Turbo Agent":
    #     settings["model"] = "gpt-3.5-turbo"
    # elif chat_profile == "GPT4 Agent":
    #     settings["model"] = "gpt-4-1106-preview"
    
    message_history = ChatMessageHistory()

    memory = ConversationBufferMemory(
        memory_key="chat_history",
        output_key="answer",
        chat_memory=message_history,
        return_messages=True,
    )

    # Create a chain that uses the Chroma vector store
    chain = ConversationalRetrievalChain.from_llm(
        ChatOpenAI(
            temperature=settings["temperature"],
            streaming=settings["streaming"],
            model=settings["model"],
        ),
        chain_type="stuff",
        retriever=vector_store.as_retriever(search_kwargs={"k": int(settings["k"])}),
        memory=memory,
        return_source_documents=True,
    )
    
    cl.user_session.set("chain", chain)
    return chain

@cl.on_chat_start
async def init():
    settings = await cl.ChatSettings(
        [
            Select(
                id="model",
                label="OpenAI - Model",
                values=[
                    "gpt-3.5-turbo",
                    # "gpt-3.5-turbo-1106",
                    # "gpt-4",
                    # "gpt-4-1106-preview",
                ],
                initial_index=0,
            ),
            Switch(id="streaming", label="OpenAI - Stream Tokens", initial=True),
            Slider(
                id="temperature",
                label="OpenAI - Temperature",
                initial=1,
                min=0,
                max=2,
                step=0.1,
            ),
            Slider(
                id="k",
                label="RAG - Retrieved Documents",
                initial=3,
                min=1,
                max=20,
                step=1,
            ),
        ]
    ).send()
    
    cl.user_session.set("settings", settings)

    get_chain()

def format_url(input_string):
    # Remove the leading '../../../'
    modified_string = input_string[9:]

    # Replace '.md' with an empty string
    modified_string = modified_string.replace('.md', '')

    # Prepend the base URL
    formatted_url = f'https://book.broomva.tech/{modified_string}'

    return formatted_url


@cl.on_message
async def main(message):
    chain = cl.user_session.get("chain")  # type: RetrievalQAWithSourcesChain

    cb = cl.AsyncLangchainCallbackHandler(
        stream_final_answer=True, answer_prefix_tokens=["FINAL", "ANSWER"]
    )

    res = await chain.acall(message.content, callbacks=[cb])

    answer = res["answer"]
    
    source_documents = res["source_documents"]  # type: List[Document]

    text_elements = []  # type: List[cl.Text]

    if source_documents:
        for source_idx, source_doc in enumerate(source_documents):
            source_name = f"Ref. {source_idx}"
            # Create the text element referenced in the message
            
            text_content = f"""{format_url(source_doc.metadata['source'])} \n
            {source_doc.page_content}
            """
            
            text_elements.append(
                cl.Text(content=text_content, name=source_name)
            )
        source_names = [text_el.name for text_el in text_elements]

        if source_names:
            answer += f"\nSources: {', '.join(source_names)}"
        else:
            answer += "\nNo sources found"

    await cl.Message(content=answer, elements=text_elements).send()