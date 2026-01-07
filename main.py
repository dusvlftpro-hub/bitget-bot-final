import ccxt
import pandas as pd
import numpy as np
import requests
import os
import json
import time
from datetime import datetime, timedelta, timezone

# 설정
TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
STATE_FILE = 'bot_memory.json'

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        # 메시지가 너무 길면 나눠서 전송 (상세 리포트라 길어질 수 있음)
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                requests.get(url, params={'chat_id': CHAT_ID, 'text': text[i:i+4000], 'parse_mode': 'HTML'})
        else:
            requests.get(url, params={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
    except: pass

def load_memory():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_memory(memory):
    with open(STATE_FILE, 'w') as f: json.dump(memory, f)

# === 🧠 지표 계산 엔진 ===
def calc_indicators(df):
    close = df['close']
    
    # 1. RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 2. CCI (20) - 요청하신 지표
    tp = (df['high'] + df['low'] + df['close']) / 3
    sma = tp.rolling(20).mean()
    mad = (tp - sma).abs().rolling(20).mean()
    df['cci'] = (tp - sma) / (0.015 * mad)

    # 3. MACD
    k = close.ewm(span=12, adjust=False).mean()
    d = close.ewm(span=26, adjust=False).mean()
    df['macd'] = k - d
    df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    # 4. 거래량 이동평균
    df['vol_ma'] = df['vol'].rolling(20).mean()
    
    # 5. VWMA 100
    df['pv'] = df['close'] * df['vol']
    df['vwma'] = df['pv'].rolling(100).sum() / df['vol'].rolling(100).sum()
    
    return df

# === 📉 인범식 채널 (Linear Regression) 계산 ===
def check_channel(df):
    y = df['close'].values
    x = np.arange(len(y))
    
    # 선형 회귀 (추세선 구하기)
    slope, intercept = np.polyfit(x, y, 1)
    regression_line = slope * x + intercept
    
    # 채널 폭(표준편차) 계산
    std_dev = np.std(y - regression_line)
    
    # 채널 하단선 (2 표준편차 아래)
    lower_channel = regression_line - (2 * std_dev)
    
    curr_price = y[-1]
    curr_lower = lower_channel[-1]
    
    # 채널 하단 근처인지 확인 (±3% 이내)
    gap = (curr_price - curr_lower) / curr_lower * 100
    
    # 하단보다 살짝 아래(-2%)거나 위(+3%)인 경우 (반등 확률 높음)
    is_bottom = -2.0 <= gap <= 3.0
    return is_bottom, gap

def run():
    print("🚀 비트겟 퀀트 종합 분석 시작...")
    bitget = ccxt.bitget({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
    
    # 분석할 시간대
    timeframes = {
        '1h': '⚡ <b>1시간봉 (단타)</b>',
        '4h': '⏰ <b>4시간봉 (스윙)</b>',
        '1d': '☀️ <b>일봉 (추세)</b>'
    }
    
    last_memory = load_memory()
    current_memory = {}
    
    # 리포트 저장소
    report = {
        'best': [],    # AI 강력 추천
        'channel': [], # 채널 하단
        'vwma': []     # VWMA 지지
    }
    
    found_any = False

    try:
        markets = bitget.load_markets()
        symbols = [s for s in markets if markets[s].get('linear') and markets[s].get('quote') == 'USDT']
        
        # 거래대금 상위 100개 코인 분석
        tickers = bitget.fetch_tickers(symbols)
        sorted_tickers = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
        top_symbols = [item[0] for item in sorted_tickers[:100]]
        
        for symbol in top_symbols:
            coin_name = markets[symbol]['base']
            
            for tf, tf_name in timeframes.items():
                try:
                    ohlcv = bitget.fetch_ohlcv(symbol, timeframe=tf, limit=120)
                    if not ohlcv or len(ohlcv) < 100: continue
                    
                    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                    df = calc_indicators(df)
                    
                    curr = df.iloc[-1]
                    prev = df.iloc[-2]
                    curr_price = curr['close']
                    
                    # ---------------------------------
                    # 1. VWMA 100 지지 확인
                    # ---------------------------------
                    if curr_price >= curr['vwma']:
                        gap_v = (curr_price - curr['vwma']) / curr['vwma'] * 100
                        if gap_v <= 3.5:
                            is_dup = (tf in last_memory and coin_name in last_memory[tf].get('vwma', []))
                            mark = "💤" if is_dup else "🔥"
                            report['vwma'].append(f"{mark} {tf} | {coin_name} (+{gap_v:.1f}%)")
                            found_any = True
                            
                            if tf not in current_memory: current_memory[tf] = {'vwma':[], 'channel':[], 'best':[]}
                            current_memory[tf]['vwma'].append(coin_name)

                    # ---------------------------------
                    # 2. 채널(Channel) 바닥 확인
                    # ---------------------------------
                    is_bottom, gap_c = check_channel(df)
                    if is_bottom:
                        is_dup = (tf in last_memory and coin_name in last_memory[tf].get('channel', []))
                        mark = "💤" if is_dup else "🌊"
                        report['channel'].append(f"{mark} {tf} | {coin_name} (하단접근)")
                        found_any = True
                        
                        if tf not in current_memory: current_memory[tf] = {'vwma':[], 'channel':[], 'best':[]}
                        current_memory[tf]['channel'].append(coin_name)

                    # ---------------------------------
                    # 3. AI 종합 점수 및 이유 생성
                    # ---------------------------------
                    score = 0
                    reasons = []
                    
                    # RSI 과매도 (30 이하) -> +2점
                    if curr['rsi'] < 30: 
                        score += 2; reasons.append(f"RSI과매도({int(curr['rsi'])})")
                    elif curr['rsi'] < 40: score += 1
                    
                    # CCI 과매도 (-100 이하) -> +1점
                    if curr['cci'] < -100: 
                        score += 1; reasons.append("CCI침체")
                        
                    # MACD 골든크로스 -> +3점
                    if curr['macd'] > curr['macd_sig'] and prev['macd'] <= prev['macd_sig']:
                        score += 3; reasons.append("MACD골든크로스")
                    elif curr['macd'] > curr['macd_sig']: score += 1 # 상승중
                        
                    # 거래량 폭발 (2배 이상) -> +2점
                    if curr['vol'] > curr['vol_ma'] * 2:
                        score += 2; reasons.append("거래량폭발")
                        
                    # 지지선 근처 가산점 -> +2점
                    if (curr_price >= curr['vwma'] and gap_v < 3) or is_bottom:
                        score += 2; reasons.append("주요지지선도달")

                    # 🏆 총점 5점 이상이면 강력 추천
                    if score >= 5:
                        is_dup = (tf in last_memory and coin_name in last_memory[tf].get('best', []))
                        mark = "💤" if is_dup else "💎"
                        reason_str = ", ".join(reasons)
                        report['best'].append(f"{mark} <b>{coin_name}</b> ({tf})\n   └ 이유: {reason_str}")
                        found_any = True
                        
                        if tf not in current_memory: current_memory[tf] = {'vwma':[], 'channel':[], 'best':[]}
                        current_memory[tf]['best'].append(coin_name)

                    time.sleep(0.05)
                except: continue

        # --- 텔레그램 리포트 작성 ---
        if found_any:
            kst = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M")
            msg = f"🦁 <b>[비트겟 퀀트 분석 리포트]</b> ({kst})\n\n"
            
            # 1. AI 추천 (제일 중요하니까 맨 위)
            if report['best']:
                msg += "🏆 <b>AI 강력 추천 (근거 확실)</b>\n"
                msg += "\n".join(report['best']) + "\n\n"
            
            # 2. 채널 하단
            if report['channel']:
                msg += "🌊 <b>채널 하단 (인범ST 반등자리)</b>\n"
                msg += "\n".join(report['channel'][:7])
                if len(report['channel']) > 7: msg += f"\n...외 {len(report['channel'])-7}개"
                msg += "\n\n"
                
            # 3. VWMA 지지
            if report['vwma']:
                msg += "📊 <b>VWMA 100선 지지</b>\n"
                msg += "\n".join(report['vwma'][:5])
                if len(report['vwma']) > 5: msg += f"\n...외 {len(report['vwma'])-5}개"

            send_msg(msg)
            save_memory(current_memory)
        else:
            save_memory({})

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
