# Simple Setup Guide for Business Judgement Bot

## Before You Start

You'll need:
- A list of your students (in Excel or CSV format)
- MongoDB Atlas account (free tier works fine)
- AI API key
- Python installed on your computer

## Step-by-Step Setup

### 1. First-Time Setup

1. **Download the Project**
   - Download the bot project files to your computer
   - Open your command prompt or terminal
   - Navigate to the project folder

2. **Set Up Your Database (One-Time Setup)**
   - Go to MongoDB Atlas website (mongodb.com)
   - Create a free account
   - Create a new cluster (the free tier is fine)
   - Click "Connect" and choose "Connect your application"
   - Copy the connection string (it looks like: `mongodb+srv://...`)
   - Save this string for later

3. **Get Your AI Key (One-Time Setup)**
   - Go to the relevant AI provider's website (e.g., OpenAI or Anthropic)
   - Create an account
   - Click on your profile → View API keys
   - Create a new key
   - Copy and save this key

4. **Configure the Project**
   - In the project folder, find the file called `.env`
   - Replace the example values with your own:
     ```
     ANTHROPIC_API_KEY=your_key_here
     MONGODB_CONNECTION_STRING=your_mongodb_string_here
     ```

### 2. Setting Up Student Access

1. **Prepare Your Student List**
   - Open Excel
   - Create a new file with these columns:
     - student_id
     - email
     - name
   - Save it as CSV (File → Save As → CSV)
   - Remember where you saved it

2. **Generate Student Identifiers**
   - In your terminal/command prompt (in the project folder):
   ```
   python scripts/generate_and_load_identifiers.py
   ```
   - When asked, provide the path to your CSV file
   - The script will create a new file with student identifiers
   - Share these identifiers with your students

### 3. Running the Application

1. **Start the Application**
   ```
   streamlit run Home.py
   ```
   - This will open the application in your web browser
   - Click deploy and set the appropriate secret variables

2. **Student Access**
   - Students use their assigned identifier to log in
   - They can then:
     1. Chat with their AI mentor

### 4. Viewing Results

- All conversations are automatically saved in your MongoDB database
- Each conversation is linked to the student's identifier

## Troubleshooting

### Common Issues

1. **"Invalid Identifier" Error**
   - Check that the student is using the correct identifier
   - Try generating new identifiers if needed

2. **Application Won't Start**
   - Make sure all the setup steps were completed
   - Check your internet connection
   - Verify your ANTHROPIC API key hasn't expired

3. **Conversation Not Saving**
   - Check your internet connection
   - Make sure students click "Finish Conversation" when done

Need help? Contact technical support at [your contact information]

# Business Judgement Bot Overview

This application consists of a simulated conversation with a middle-manager mentor where students can practice making and justifying business judgements 

### How It Works

1. Students log in using their unique identifier
2. The mentor, Em, engages in conversation with the student
3. All conversations are saved to MongoDB for review

## Setup Instructions

### 1. Environment Setup

1. Clone the repository
2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\Activate.ps1
```
3. Install requirements:
```bash
pip install -r requirements.txt
```

### 2. Configuration

1. Create a `.env` file in the project root with the following:
```properties
ANTHROPIC_API_KEY=your_anthropic_api_key
MONGODB_USERNAME=your_mongodb_username
MONGODB_PASSWORD=your_mongodb_password
MONGODB_CONNECTION_STRING=your_mongodb_connection_string
```

2. Create a `.streamlit/secrets.toml` file:
```toml
ANTHROPIC_API_KEY="your_anthropic_api_key"
MONGODB_CONNECTION_STRING="your_mongodb_connection_string"
```

### 3. Setting Up Student Identifiers

1. Create a CSV file with student information (e.g., `students.csv`):
```csv
student_id,email,name
12345,student1@example.com,John Doe
12346,student2@example.com,Jane Smith
```

2. Generate identifiers and load them into MongoDB:
```bash
python scripts/generate_and_load_identifiers.py
```

3. The script will:
   - Generate unique identifiers for each student
   - Save a new CSV with the mappings (keep this secure!)
   - Upload only the identifiers to MongoDB

### 4. Running the Application

1. Start the Streamlit app:
```bash
streamlit run Home.py
```

2. Access the application at `http://localhost:8501`

## Project Structure

```
business-judgement-bot/
├── Home.py                   # Main application entry point
├── pages/
│   └── 1_Em_Conversation.py  # Mentorship conversation with Em
├── utils/
│   └── mongodb.py            # Database utilities
├── scripts/
    ├── create_index.py       # Indexes reference data
│   └── generate_and_load_identifiers.py  # Identifier management
└── prompts/
    └── emprompt.txt          # Em conversation prompt
└── reference_data/           # Contains relevant reference files for indexing
└── storage/                  # Index storage
```

## Security Considerations

1. Never commit `.env` or `secrets.toml` files
2. Keep the CSV with student-identifier mappings secure
3. Only identifiers are stored in MongoDB, no personal information
4. Regular database backups are recommended

## Troubleshooting

1. Invalid Identifier:
   - Ensure the identifier was generated using the provided script
   - Check MongoDB connection
   - Verify the identifier in the valid_identifiers collection

2. Connection Issues:
   - Verify MongoDB connection string
   - Check internet connection
   - Ensure AI API key is valid

3. Missing Conversations:
   - Check MongoDB connection
   - Verify the conversation was properly finished using the "Finish Conversation" button

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

This repository is available for unlimited public use
