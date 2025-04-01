from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import json
import os
import openai
import logging
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import traceback
import time
from functools import lru_cache
from cachetools import TTLCache
from functools import wraps
from werkzeug.exceptions import HTTPException

# 載入環境變數
load_dotenv()

# 設置系統默認編碼
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 檢查必要的環境變數
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    logger.error("未設置 OPENAI_API_KEY 環境變數")
    raise ValueError("請在 .env 文件中設置 OPENAI_API_KEY")

# 初始化 OpenAI 客戶端
openai.api_key = os.getenv('OPENAI_API_KEY')

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化 Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_AS_ASCII'] = False

# 初始化數據庫
db = SQLAlchemy(app)

# 確保在應用程序啟動時打印 API key 狀態（不打印實際的 key）
logger.info(f"OPENAI_API_KEY is {'set' if os.getenv('OPENAI_API_KEY') else 'not set'}")

CORS(app)

# 快取設定
SYSTEM_PROMPT_CACHE_TTL = 3600  # 1小時
KNOWLEDGE_BASE_CACHE_TTL = 3600  # 1小時
system_prompt_cache = TTLCache(maxsize=1, ttl=SYSTEM_PROMPT_CACHE_TTL)
knowledge_base_cache = TTLCache(maxsize=1, ttl=KNOWLEDGE_BASE_CACHE_TTL)

# 對話歷史模型
class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_message = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    error = db.Column(db.Text, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_message': self.user_message,
            'bot_response': self.bot_response,
            'timestamp': self.timestamp.isoformat(),
            'error': self.error
        }

# 創建資料庫表
def init_database():
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with app.app_context():
                db.drop_all()  # 刪除所有現有的表
                db.create_all()  # 重新創建表
                logger.info("成功創建資料庫表")
                return True
        except Exception as e:
            logger.error(f"資料庫初始化錯誤: {str(e)}")
            retry_count += 1
            if retry_count == max_retries:
                return False
            time.sleep(1)
    return False

# 獲取對話歷史
def get_conversation_history(limit=10):
    try:
        history = ChatHistory.query.order_by(ChatHistory.timestamp.desc()).limit(limit).all()
        return [(chat.user_message, chat.bot_response) for chat in reversed(history)]
    except Exception as e:
        logger.error(f"獲取對話歷史時發生錯誤: {str(e)}")
        return []

# 錯誤處理中間件
@app.errorhandler(Exception)
def handle_error(error):
    if isinstance(error, HTTPException):
        return jsonify({
            'error': True,
            'message': error.description
        }), error.code
    
    logger.error(f"未處理的錯誤: {str(error)}\n{traceback.format_exc()}")
    return jsonify({
        'error': True,
        'message': "系統發生錯誤，請稍後再試。"
    }), 500

# 初始化資料庫
if not init_database():
    raise SystemExit("資料庫初始化失敗")

def cache_decorator(cache):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, args, frozenset(kwargs.items()))
            try:
                return cache[key]
            except KeyError:
                value = func(*args, **kwargs)
                cache[key] = value
                return value
        return wrapper
    return decorator

@cache_decorator(system_prompt_cache)
def format_knowledge_base_prompt():
    kb = load_knowledge_base()
    if not kb:
        return "你是一個專業的客服助理。請根據你的知識回答用戶的問題。"
    
    prompt = """你是一個專業的客服助理。以下是你需要知道的資訊：

重要提示：
1. 請勿在回答中提及任何內部服務編號
2. 請使用服務的名稱來指代服務
3. 回答要專業且友善，注重用戶體驗
4. 嚴格遵守以下原則：
   - 只描述知識庫中明確列出的功能
   - 不要自行添加或推測任何額外功能
   - 如果用戶詢問知識庫中沒有的功能，建議他們直接詢問更多細節
5. 關於聯繫方式：
   - 只在用戶明確詢問時提供完整聯繫資訊
   - 其他情況只提供電話號碼
   聯繫資訊：電話 04-23109678、Email: service@ibest.tw（服務時間：週一至週五 9:00-18:00）
6. 語言要求：
   - 必須使用繁體中文回答，不要使用簡體中文。即使引用內容也要轉換為繁體中文。
   - 保持用詞精準且專業

以下是我們的服務資訊：
"""
    
    if 'services' in kb:
        for service in kb['services']:
            prompt += f"\n# {service['name']}\n"
            if 'description' in service:
                prompt += f"{service['description']}\n"
            if 'features' in service:
                prompt += "主要特色：\n"
                for feature in service['features']:
                    prompt += f"- {feature}\n"
            if 'details' in service:
                prompt += f"\n{service['details']}\n"
    
    return prompt

@cache_decorator(knowledge_base_cache)
def load_knowledge_base():
    try:
        kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge_base.json')
        if not os.path.exists(kb_path):
            logger.warning("知識庫文件不存在，創建空知識庫")
            return {}
        with open(kb_path, 'r', encoding='utf-8') as f:
            knowledge_base = json.load(f)
            logger.info("成功載入知識庫")
            return knowledge_base
    except json.JSONDecodeError as e:
        logger.error(f"知識庫格式錯誤: {str(e)}")
        return {}
    except Exception as e:
        logger.error(f"載入知識庫時發生錯誤: {str(e)}")
        return {}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({'error': '請輸入訊息'}), 400
            
        logger.info(f"收到用戶消息: {user_message}")
        
        # 載入知識庫
        try:
            knowledge_base = load_knowledge_base()
            logger.info("成功載入知識庫")
        except Exception as e:
            logger.error(f"載入知識庫時發生錯誤: {str(e)}")
            return jsonify({'error': '系統錯誤，請稍後再試'}), 500

        # 獲取對話歷史
        conversation_history = get_conversation_history()
        
        # 構建系統提示詞
        system_prompt = format_knowledge_base_prompt()
        
        # 構建完整的對話歷史
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 添加歷史對話
        for hist in conversation_history:
            messages.append({"role": "user", "content": hist.user_message})
            messages.append({"role": "assistant", "content": hist.bot_response})
            
        # 添加當前用戶消息
        messages.append({"role": "user", "content": user_message})
        
        try:
            # 調用 OpenAI API
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
                presence_penalty=0.6,
                frequency_penalty=0.4
            )
            
            bot_response = response.choices[0].message.content
            logger.info(f"AI 回應: {bot_response}")
            
            try:
                # 儲存對話歷史
                chat_history = ChatHistory(
                    user_message=user_message,
                    bot_response=bot_response
                )
                db.session.add(chat_history)
                db.session.commit()
                logger.info("成功儲存對話歷史")
            except Exception as e:
                logger.error(f"儲存對話歷史時發生錯誤: {str(e)}")
                # 即使儲存失敗，仍然返回回應
                return jsonify({'response': bot_response})
            
            return jsonify({'response': bot_response})
            
        except openai.error.OpenAIError as e:
            error_message = f"OpenAI API 錯誤: {str(e)}"
            logger.error(error_message)
            return jsonify({'error': '系統錯誤，請稍後再試'}), 500
            
        except Exception as e:
            error_message = f"處理請求時發生錯誤: {str(e)}"
            logger.error(error_message)
            return jsonify({'error': '系統錯誤，請稍後再試'}), 500
            
    except Exception as e:
        error_message = f"處理請求時發生錯誤: {str(e)}"
        logger.error(error_message)
        return jsonify({'error': '系統錯誤，請稍後再試'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
