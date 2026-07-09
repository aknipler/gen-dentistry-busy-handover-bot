from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
from datetime import datetime
import streamlit as st

def get_mongo_client(connection_string):
    return MongoClient(connection_string, server_api=ServerApi('1'))

def check_identifier(connection_string, identifier):
    """Check if the identifier exists in the valid_identifiers collection."""
    client = get_mongo_client(connection_string)
    db = client[st.session_state.get("mongodb_database_name")]
    try: 
        result = db.valid_identifiers.find_one({"identifier": identifier})
        return bool(result)
    finally:
        client.close()

def log_transcript(connection_string, conversation_type, messages, collection):
    client = get_mongo_client(connection_string)
    db = client[st.session_state.get("mongodb_database_name")]
    collection = db[collection]

    try:
        # Create new document for previous conversation
        document = {
            "timestamp": datetime.utcnow(),
            "em_messages": messages,
            "identifier": st.session_state.get("user_identifier", "anonymous")
        }
        result = collection.insert_one(document)
        return str(result.inserted_id)
        
    finally:
        client.close()


def get_latest_transcript(connection_string, database_name, collection, identifier):
    """Return the most recent transcript document for an identifier.

    Used by the voice (Pipecat) flow: the bot process writes the transcript to
    MongoDB on hangup, and the Streamlit page reads it back here to hand off to
    the feedback stage. Returns None if nothing has been saved yet.
    """
    client = get_mongo_client(connection_string)
    db = client[database_name]
    try:
        return db[collection].find_one(
            {"identifier": identifier}, sort=[("timestamp", -1), ("_id", -1)]
        )
    finally:
        client.close()


def get_latest_transcript_since(connection_string, database_name, collection, identifier, min_timestamp):
    """Return the most recent transcript for an identifier at/after min_timestamp."""
    client = get_mongo_client(connection_string)
    db = client[database_name]
    try:
        return db[collection].find_one(
            {"identifier": identifier, "timestamp": {"$gte": min_timestamp}},
            sort=[("timestamp", -1), ("_id", -1)],
        )
    finally:
        client.close()


def get_transcript(connection_string, database_name, collection, transcript_id):
    mongo_client = get_mongo_client(connection_string)
    db = mongo_client[database_name]
    collection = db[collection]

    try:
        # Retrieve the transcript by its ObjectId
        transcript = collection.find_one({"_id": ObjectId(transcript_id)})
        return transcript
    finally:
        mongo_client.close()
