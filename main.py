import ccxt
import pandas as pd
import requests
import os
import json
import time
from datetime import datetime, timedelta, timezone

# 설정 불러오기
TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
STATE_FILE = 'bot_memory.json'

def send_msg(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.get(url, params={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
    except:
        pass

def load_memory():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_memory(memory):
    with open(STATE_FILE, 'w') as f: json.dump(memory, f)

def run():
    print("🚀 비트겟 선물 확장 탐색 (Top 150 + 1시간봉)...")
    
    # 속도 제한 준수 모드 켜기
    bitget = ccxt.bitget({
        'options': {'defaultType': 'swap'},
        'enableRateLimit': True
    })
    
    # ⭐ [업그레이드 1] 1시간봉(단타) 추가 -> 결과가 자주 바뀜
    timeframes = {
        '1h': '⚡ <b>1시간봉 (단타)</b>',
        '4h': '⏰ <b>4시간봉 (단기)</b>',
        '1d': '☀️ <b>일봉 (중기)</b>', 
        '1w': '🗓 <b>주봉 (장기)</b>'
    }
    
    last_memory = load_memory()
    current_memory = {}
    report = {tf: [] for tf in timeframes}
    found_any = False

    try:
        markets = bitget.load_markets()
        symbols = [
            s for s in markets 
            if markets[s].get('linear') == True 
            and markets[s].get('type') == 'swap' 
            and markets[s].get('quote') == 'USDT'
        ]
        
        tickers = bitget.fetch_tickers(symbols)
        # 거래대금 많은 순으로 정렬
        sorted_tickers = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
        
        # ⭐ [업그레이드 2] 상위 50개 -> 150개로 확장 (중소형 알트 포착)
        top_symbols = [item[0] for item in sorted_tickers[:150]]
        
        for symbol in top_symbols:
            coin_name = markets[symbol]['base']
            
            for tf, label in timeframes.items():
                try:
                    ohlcv = bitget.fetch_ohlcv(symbol, timeframe=tf, limit=120)
                    if not ohlcv or len(ohlcv) < 100: continue
                    
                    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                    
                    df['pv'] = df['close'] * df['vol']
                    vwma_100 = df['pv'].rolling(100).sum() / df['vol'].rolling(100).sum()
                    
                    curr_price = df['close'].iloc[-1]
                    curr_vwma = vwma_100.iloc[-1]
                    
                    if curr_price >= curr_vwma:
                        gap = (curr_price - curr_vwma) / curr_vwma * 100
                        
                        # ⭐ [업그레이드 3] 3% -> 5%로 조건 완화 (더 많이 잡힘)
                        if gap <= 5.0:
                            is_dup = False
                            if tf in last_memory and coin_name in last_memory[tf]:
                                is_dup = True
                            
                            # 중복이면 아이콘 간소화 (깔끔하게)
                            mark = "💤" if is_dup else "🔥"
                            
                            line = f"{mark} {coin_name} (+{gap:.1f}%)"
                            report[tf].append(line)
                            found_any = True
                            
                            if tf not in current_memory: current_memory[tf] = []
                            current_memory[tf].append(coin_name)
                    
                    time.sleep(0.05) # API 차단 방지
                except:
                    continue
        
        if found_any:
            kst_now = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M")
            msg = f"🦁 <b>[비트겟 선물 탐지기]</b> ({kst_now})\n"
            msg += "범위: Top 150 / 조건: 5% 이내\n"
            
            order = ['1h', '4h', '1d', '1w'] # 출력 순서
            has_content = False

            for tf in order:
                items = report[tf]
                if items:
                    msg += f"\n{timeframes[tf]}\n"
                    msg += "-" * 15 + "\n"
                    
                    # 내용이 너무 길면 15개만 보여주고 자르기 (스팸 방지)
                    for item in items[:15]:
                        msg += f"{item}\n"
                    if len(items) > 15:
                        msg += f"...외 {len(items)-15}개 더 있음\n"
                        
                    has_content = True
            
            if has_content:
                send_msg(msg)
            save_memory(current_memory)
        else:
            save_memory({})

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
