import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

load_dotenv()

def test_llm():
    api_key = os.environ.get("GOOGLE_API_KEY")
    model = "gemini-2.5-pro"
    
    print(f"Testing with model: {model}")
    
    llm = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key
    )
    
    messages = [HumanMessage(content="Hello!")]
    try:
        response = llm.invoke(messages)
        print(f"Success! Response: {response.content}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_llm()
