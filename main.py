import ccxt
import pandas as pd
import requests
import os
import json
import time
from datetime import datetime, timedelta, timezone

# 1. 깃허브 금고에서 열쇠 꺼내기
TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
STATE_FILE = 'bot_memory.json'

def send_msg(text):
    """텔레그램 메시지 전송 (표 형식 지원)"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.get(url, params={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
    except Exception as e:
        print(f"전송 실패: {e}")

def load_memory():
    """지난번 기억 불러오기"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_memory(memory):
    """이번 기억 저장하기"""
    with open(STATE_FILE, 'w') as f:
        json.dump(memory, f)

def run():
    print("🚀 비트겟 [선물] 시장 분석 시작...")
    
    # ⭐ 핵심 변경: 선물(Swap) 시장 데이터 가져오기 설정
    bitget = ccxt.bitget({
        'options': {'defaultType': 'swap'} 
    })
    
    # 3가지 시간대 설정 (4시간, 일봉, 주봉)
    timeframes = {
        '4h': '⏰ <b>4시간봉 (단기)</b>',
        '1d': '☀️ <b>일봉 (중기)</b>', 
        '1w': '🗓 <b>주봉 (장기)</b>'
    }
    
    last_memory = load_memory()  # 과거 기억
    current_memory = {}          # 현재 기억 (새로 저장할 것)
    report = {tf: [] for tf in timeframes} # 결과 리포트용
    found_any = False

    try:
        # 선물 마켓 정보 로드
        markets = bitget.load_markets()
        
        # ⭐ [필터링] USDT 무기한 선물(Linear Perpetual)만 골라내기
        # Coin-M(반대매매) 선물은 제외하고 USDT 선물만 봅니다.
        symbols = [
            s for s in markets 
            if markets[s].get('linear') == True     # USDT 마진(Linear)
            and markets[s].get('type') == 'swap'    # 선물(Swap)
            and markets[s].get('quote') == 'USDT'   # 결제 화폐가 USDT
        ]
        
        # 거래량 상위 50개 코인 추출 (선물은 거래대금 순위가 중요)
        tickers = bitget.fetch_tickers(symbols)
        sorted_tickers = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
        top_symbols = [item[0] for item in sorted_tickers[:50]]
        
        print(f"거래량 상위 {len(top_symbols)}개 선물 코인 감시 중...")

        for symbol in top_symbols:
            # 코인명 깔끔하게 정리 (예: BTC/USDT:USDT -> BTC)
            coin_name = markets[symbol]['base']
            
            # 각 시간봉별로 체크
            for tf, label in timeframes.items():
                try:
                    ohlcv = bitget.fetch_ohlcv(symbol, timeframe=tf, limit=120)
                    if not ohlcv or len(ohlcv) < 100: continue
                    
                    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                    
                    # VWMA 100 계산
                    df['pv'] = df['close'] * df['vol']
                    vwma_100 = df['pv'].rolling(100).sum() / df['vol'].rolling(100).sum()
                    
                    curr_price = df['close'].iloc[-1]
                    curr_vwma = vwma_100.iloc[-1]
                    
                    # 조건: 가격 >= VWMA (지지) 이고, 이격도 3% 이내
                    if curr_price >= curr_vwma:
                        gap = (curr_price - curr_vwma) / curr_vwma * 100
                        
                        if gap <= 3.0: # 3% 이내 타이트하게 (선물 타점)
                            # 중복 체크 (지난번 기억에 있었는지?)
                            is_dup = False
                            if tf in last_memory and coin_name in last_memory[tf]:
                                is_dup = True
                            
                            # 표시 마크
                            mark = "💤중복" if is_dup else "🔥<b>NEW</b>"
                            
                            # 결과 한 줄 만들기
                            line = f"{mark} | {coin_name} (+{gap:.2f}%)"
                            report[tf].append(line)
                            found_any = True
                            
                            # 이번 기억에 추가
                            if tf not in current_memory: current_memory[tf] = []
                            current_memory[tf].append(coin_name)
                    
                    time.sleep(0.05) # 차단 방지
                except:
                    continue
        
        # 전송 로직
        if found_any:
            kst_now = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M")
            
            msg = f"🦁 <b>[비트겟 선물 VWMA 100]</b> ({kst_now})\n"
            msg += "조건: 3% 이내 지지 (롱 타점)\n"
            
            order = ['4h', '1d', '1w']
            has_content = False
            
            for tf in order:
                items = report[tf]
                if items:
                    msg += f"\n{timeframes[tf]}\n"
                    msg += "-" * 20 + "\n"
                    for item in items:
                        msg += f"{item}\n"
                    has_content = True
            
            if has_content:
                send_msg(msg)
                
            save_memory(current_memory)
        else:
            print("조건 만족 없음. 기억 초기화.")
            save_memory({})

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
