import os
import psycopg2
import chromadb
from sentence_transformers import SentenceTransformer
from flask import Flask, request, jsonify

embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
chroma_client = chromadb.Client()
snn_memory_collection = chroma_client.get_or_create_collection(name="snn_memory")

def get_postgres_connection():
    conn = psycopg2.connect(
        dbname="elara_memory",
        user="elara_user",
        password="your_secure_password",
        host="localhost",
        port="5432"
    )
    return conn

def setup_database():
    conn = get_postgres_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            id SERIAL PRIMARY KEY,
            message_id VARCHAR(255) UNIQUE NOT NULL,
            author VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS learned_facts (
            id SERIAL PRIMARY KEY,
            topic VARCHAR(255) NOT NULL,
            fact TEXT NOT NULL,
            source VARCHAR(255),
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

app = Flask(__name__)

@app.route('/store_message', methods=['POST'])
def store_message():
    data = request.json
    message_id, author, content = data.get('message_id'), data.get('author'), data.get('content')

    if not all([message_id, author, content]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conversation_history (message_id, author, content) VALUES (%s, %s, %s) ON CONFLICT (message_id) DO NOTHING;",
            (message_id, author, content)
        )
        conn.commit()
        cur.close()
        conn.close()

        embedding = embedding_model.encode(content).tolist()
        snn_memory_collection.add(
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"author": author}],
            ids=[message_id]
        )
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"[DB ERROR] Failed to store message: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/store_fact', methods=['POST'])
def store_fact():
    data = request.json
    topic, fact, source = data.get('topic'), data.get('fact'), data.get('source', 'Classroom')

    if not all([topic, fact]):
        return jsonify({"error": "Missing topic or fact"}), 400

    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO learned_facts (topic, fact, source) VALUES (%s, %s, %s);",
            (topic, fact, source)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "fact stored"}), 200
    except Exception as e:
        print(f"[DB ERROR] Failed to store fact: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/retrieve_memories', methods=['POST'])
def retrieve_memories():
    data = request.json
    query_text = data.get('query')
    if not query_text:
        return jsonify({"error": "Query text is required"}), 400

    retrieved_memories = {"conversations": [], "facts": []}

    try:
        query_embedding = embedding_model.encode(query_text).tolist()
        conversation_results = snn_memory_collection.query(
            query_embeddings=[query_embedding],
            n_results=3
        )
        if conversation_results and conversation_results['documents']:
            docs = conversation_results['documents'][0]
            metadatas = conversation_results['metadatas'][0]
            for i, doc in enumerate(docs):
                retrieved_memories["conversations"].append(f"{metadatas[i]['author']}: {doc}")

        conn = get_postgres_connection()
        cur = conn.cursor()
        query_words = query_text.lower().split()
        sql_query = "SELECT fact FROM learned_facts WHERE " + " OR ".join(["LOWER(fact) LIKE %s"] * len(query_words)) + " LIMIT 3;"
        sql_params = [f"%{word}%" for word in query_words]
        cur.execute(sql_query, sql_params)
        fact_results = cur.fetchall()
        for row in fact_results:
            retrieved_memories["facts"].append(row[0])
        cur.close()
        conn.close()

        return jsonify(retrieved_memories), 200

    except Exception as e:
        print(f"[RAG ERROR] Failed to retrieve memories: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    setup_database()
    app.run(host='0.0.0.0', port=5001)
