import pandas as pd
from pymongo import MongoClient
from pymongo.server_api import ServerApi
import os
from datetime import datetime
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_mongo_client(connection_string):
    return MongoClient(connection_string, server_api=ServerApi('1'))

def load_identifiers(csv_path, connection_string, database_name):
    """
    Load identifiers from CSV file into MongoDB.
    Expected CSV format: Must have a column named 'identifier'
    """
    try:
        # Read CSV file
        df = pd.read_csv(csv_path)
        
        if 'identifier' not in df.columns:
            raise ValueError("CSV must contain 'identifier' column")

        # Connect to MongoDB
        client = get_mongo_client(connection_string)
        if(input("Is the MongoDB Database name '" + database_name + "' correct?").strip() == ("yes" or "y" or "Y" or "Yes")):
            exit()
        db = database_name
        collection = db.valid_identifiers

        # Clear existing identifiers if needed
        should_clear = input("Clear existing identifiers? (y/n): ").lower() == 'y'
        if should_clear:
            collection.delete_many({})
            logging.info("Cleared existing identifiers")

        # Prepare documents
        documents = []
        for identifier in df['identifier'].unique():
            if pd.notna(identifier):  # Skip empty/NaN values
                documents.append({
                    "identifier": str(identifier).strip(),
                    "created_at": datetime.utcnow()
                })

        # Insert documents
        if documents:
            collection.insert_many(documents)
            logging.info(f"Successfully loaded {len(documents)} identifiers")
        else:
            logging.warning("No valid identifiers found in CSV")

    except Exception as e:
        logging.error(f"Error loading identifiers: {str(e)}")
        raise
    finally:
        if 'client' in locals():
            client.close()

if __name__ == "__main__":
    # Load environment variables
    load_dotenv()
    
    # Get MongoDB connection string
    connection_string = os.getenv("MONGODB_CONNECTION_STRING")
    database_name = os.getenv("MONGODB_DATABASE_NAME")
    if not connection_string:
        raise ValueError("MONGODB_CONNECTION_STRING not found in environment variables")
    if not database_name:
        raise ValueError("MONGODB_DATABASE_NAME not found in environment variables")

    # Get CSV path from command line argument or use default
    csv_path = input("Enter path to CSV file: ").strip()
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    load_identifiers(csv_path, connection_string, database_name)
