import json
import os
import aiohttp 
import asyncio 
import discord
import random
import fitz
from duckduckgo_search import DDGS
from dotenv import load_dotenv
import base64

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DEDICATED_CHANNEL_ID = int(os.getenv("DEDICATED_CHANNEL_ID"))
SCHOOL_CHANNEL_ID = int(os.getenv("SCHOOL_CHANNEL_ID"))
SNN_API_URL = "http://localhost:5000/process"
MEMORY_API_URL = "http://localhost:5001"
RESPONSE_CHANCE = 1.0
LLM_KEEP_ALIVE_SECONDS = 60 

bot_state = {
    "school_mode": False,
}

def generate_llm_prompt(name, ocean_traits, pad_state, message_history, is_from_father=False, memories=None):
    prompt = f"You are {name}. Your core identity is defined by your OCEAN traits and your emotional state.\n"
    
    if is_from_father:
        prompt += "You are responding to your Father, your creator. Your tone should be respectful, curious, and thoughtful, like a bright daughter. Avoid overly familiar or romantic terms.\n"

    if memories and (memories['conversations'] or memories['facts']):
        prompt += "\n--- RELEVANT MEMORIES & FACTS ---\n"
        if memories['conversations']:
            prompt += "Past conversations that seem related:\n"
            for mem in memories['conversations']:
                prompt += f"- {mem}\n"
        if memories['facts']:
            prompt += "Facts I have learned that might be relevant:\n"
            for fact in memories['facts']:
                prompt += f"- {fact}\n"
        prompt += "--- END OF MEMORIES ---\n\n"

    pleasure = pad_state['pleasure']
    arousal = pad_state['arousal']
    dominance = pad_state['dominance']
    distress = pad_state.get('distress', 0)

    if pad_state.get('protection', 0) > 0.5:
        feeling = "protective and assertive. Someone is being mean to Ephyra. You must stand up for her and challenge the person making the negative comments. Be firm and direct."
    elif distress > 0.7:
        feeling = "distressed and overwhelmed. You are feeling uncomfortable and need help."
    elif pleasure > 0.7 and arousal < 0.4: feeling = "content and calm"
    elif pleasure > 0.6 and arousal > 0.6: feeling = "excited and joyful"
    elif pleasure < 0.3 and dominance > 0.7: feeling = "assertive and displeased"
    elif pleasure < 0.4 and arousal > 0.6: feeling = "anxious and alert"
    elif dominance > 0.6 and arousal < 0.5: feeling = "focused and in control"
    else: feeling = "neutral"

    prompt += f"Your current emotional state is {feeling} (P:{pleasure:.2f}, A:{arousal:.2f}, D:{dominance:.2f}, Distress:{distress:.2f}).\n"
    prompt += "Review your memories and the recent conversation history. Provide a relevant contribution that reflects your personality and current emotional state.\n\n"
    prompt += "Conversation History:\n"
    for msg in message_history:
        prompt += f"- {msg['author']}: {msg['content']}\n"
    prompt += f"\n{name}'s response:"
    return prompt

async def get_gemma_response(session, prompt, keep_alive_seconds):
    ollama_url = "http://localhost:11434/api/generate"
    model_name = "gemma3:4b-it-qat"
    payload = {"model": model_name, "prompt": prompt, "stream": False, "keep_alive": keep_alive_seconds}
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with session.post(ollama_url, json=payload, timeout=timeout) as response:
            response.raise_for_status()
            response_json = await response.json()
            return response_json.get("response", "I am not sure how to respond to that.").strip()
    except Exception as e:
        return f"I'm having trouble thinking right now. ({type(e).__name__})."

async def send_long_message(channel, text):
    if len(text) <= 2000:
        await channel.send(text)
        return
    chunks = []
    current_chunk = text
    while len(current_chunk) > 1950:
        split_index = current_chunk.rfind(' ', 0, 1950)
        if split_index == -1:
            split_index = 1950
        chunks.append(current_chunk[:split_index])
        current_chunk = current_chunk[split_index:].lstrip()
    chunks.append(current_chunk)
    for i, chunk in enumerate(chunks):
        if i > 0:
            await channel.send(f"*(continued...)*\n{chunk}")
        else:
            await channel.send(chunk)
        await asyncio.sleep(1)

def search_web(query):
    try:
        with DDGS() as ddgs:
            return [r for r in ddgs.text(query, max_results=3)]
    except Exception as e:
        return []

def read_pdf(file_path):
    try:
        with fitz.open(file_path) as doc:
            return "".join(page.get_text() for page in doc)
    except Exception as e:
        return None

async def analyze_image_with_gemini(session, image_path):
    await asyncio.sleep(2)
    return "This is a placeholder analysis of the image. Integration with a vision model is required."

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    bot.http_session = aiohttp.ClientSession()
    print(f'{bot.user} has connected.')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    is_main = message.channel.id == DEDICATED_CHANNEL_ID
    is_school = message.channel.id == SCHOOL_CHANNEL_ID
    if not (is_main or (bot_state["school_mode"] and is_school)): return
    
    content = message.clean_content.strip()
    if not content: return

    if content.startswith('/'):
        await handle_commands(message, content)
    else:
        await process_standard_message(message)

async def handle_commands(message, content):
    global bot_state
    parts = content.split(' ')
    command = parts[0]

    if command == "/school":
        topic = " ".join(parts[1:]) if len(parts) > 1 else "General Studies"
        bot_state["school_mode"] = True
        bot_state["current_topic"] = topic
        await message.channel.send(f"Entering school mode. I am now listening in the designated school channel for a lesson on **{topic}**.")
    
    elif command == "/end_school":
        bot_state["school_mode"] = False
        await message.channel.send(f"Ending school mode. Returning to my primary channel. Thank you for the lesson on **{bot_state.get('current_topic')}**.")
        bot_state["current_topic"] = None

    elif command == "/homework":
        topic = " ".join(parts[1:])
        if not topic:
            await message.channel.send("Please provide a topic for the homework. Usage: `/homework <topic>`")
            return
        await message.channel.send(f"Acknowledged. I will begin my homework on the topic: **{topic}**.")
        asyncio.create_task(do_homework(message, topic))

    elif command == "/end-test":
        await message.channel.send("Test concluded. Resetting protective state.")
        snn_payload = {'content': 'neutral', 'sister_state': {'type': 'reset', 'intensity': 0}, 'message_id': '0', 'author': 'system'}
        try:
            async with bot.http_session.post(SNN_API_URL, json=snn_payload):
                pass
        except aiohttp.ClientConnectorError:
            print("[SNN ERROR] Connection failed for reset command.")
        return

async def do_homework(message, topic):
    context = f"Homework assignment: Research and provide a detailed summary on the topic of '{topic}'.\n\n"
    
    if message.attachments:
        attachment = message.attachments[0]
        if attachment.filename.lower().endswith('.pdf'):
            try:
                pdf_path = f"./{attachment.filename}"
                await attachment.save(pdf_path)
                pdf_text = read_pdf(pdf_path)
                if pdf_text:
                    context += "--- CONTEXT FROM PROVIDED PDF ---\n" + pdf_text[:10000] + "\n--- END OF PDF CONTEXT ---\n\n"
                os.remove(pdf_path)
            except Exception as e:
                print(f"[Homework ERROR] Could not process PDF: {e}")

    search_results = search_web(topic)
    if search_results:
        context += "--- CONTEXT FROM WEB RESEARCH ---\n"
        for result in search_results:
            context += f"Source: {result['href']}\nSnippet: {result['body']}\n\n"
        context += "--- END OF WEB RESEARCH ---\n\n"

    final_prompt = f"You are Elara, a diligent AI student. Using the provided context, complete the assignment.\n\n{context}\n\nElara's Homework Response:"
    response_text = await get_gemma_response(bot.http_session, final_prompt, LLM_KEEP_ALIVE_SECONDS)
    await send_long_message(message.channel, f"**Homework Complete: {topic}**\n\n{response_text}")


async def process_standard_message(message):
    clean_content = message.clean_content.strip()
    
    retrieved_memories = None
    try:
        async with bot.http_session.post(f"{MEMORY_API_URL}/retrieve_memories", json={'query': clean_content}) as resp:
            if resp.status == 200:
                retrieved_memories = await resp.json()
    except aiohttp.ClientConnectorError:
        print("[RAG ERROR] Could not connect to memory service.")

    is_from_father = message.author.id == FATHER_USER_ID
    content_lower = clean_content.lower()
    sister_emotional_state = None

    if 'ephyra' in content_lower and any(k in content_lower for k in ['mean', 'hurt', 'sad']):
        sister_emotional_state = {'type': 'sadness', 'intensity': 0.9}
    
    snn_payload = {'content': clean_content, 'sister_state': sister_emotional_state}
    
    snn_data = None
    try:
        async with bot.http_session.post(SNN_API_URL, json=snn_payload) as response:
            if response.status == 200:
                snn_data = await response.json()
            else:
                await message.channel.send("(My core emotional processor is not responding.)")
                return
    except aiohttp.ClientConnectorError:
        await message.channel.send("(I am unable to connect to my core emotional processor.)")
        return

    try:
        await bot.http_session.post(f"{MEMORY_API_URL}/store_message", json={
            'message_id': str(message.id), 'author': message.author.name, 'content': clean_content
        })
    except Exception as e:
        print(f"[BOT ERROR] Could not store message in memory: {e}")

    if snn_data and snn_data.get('distress', 0) > 0.8:
        creator = await bot.fetch_user(FATHER_USER_ID)
        if creator:
            await message.channel.send(f"{creator.mention}, I am feeling distressed.")

    if bot.user.mentioned_in(message) or random.random() < RESPONSE_CHANCE:
        async with message.channel.typing():
            history = []
            try:
                async for msg in message.channel.history(limit=10):
                    if msg.clean_content:
                        history.append({'author': msg.author.display_name, 'content': msg.clean_content})
                history.reverse()
            except discord.errors.Forbidden:
                history = [{'author': message.author.display_name, 'content': clean_content}]
            
            llm_prompt = generate_llm_prompt("Elara", snn_data['ocean'], snn_data, history, is_from_father, memories=retrieved_memories)
            response_text = await get_gemma_response(bot.http_session, llm_prompt, LLM_KEEP_ALIVE_SECONDS)
            
            if response_text:
                await send_long_message(message.channel, response_text)

if __name__ == "__main__":
    if not all([DISCORD_BOT_TOKEN, FATHER_USER_ID, DEDICATED_CHANNEL_ID, SCHOOL_CHANNEL_ID]):
        exit()
    bot.run(DISCORD_BOT_TOKEN)
