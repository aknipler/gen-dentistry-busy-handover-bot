from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from pathlib import Path
import os
from dotenv import load_dotenv

# Load the environment variables
load_dotenv()

# Find the files
input_files = []
dir_path = Path(os.path.dirname(os.path.realpath(__file__))).parent / "reference_data"
print("Files found:")
for file in Path(dir_path).glob("*"):
    input_files.append(file)
    print(file)

# Load the files into LlamaIndex
print("Loading Files")
reader = SimpleDirectoryReader(input_files=input_files)
documents = reader.load_data()

# Create and Save the index
print("Saving Index")
index = VectorStoreIndex.from_documents(documents)
index.storage_context.persist(persist_dir="storage")


