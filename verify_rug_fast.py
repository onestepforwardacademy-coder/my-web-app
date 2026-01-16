#!/usr/bin/env python3
import sys
import requests

if len(sys.argv) < 2:
    print("ERROR: No token address")
    sys.exit(1)

token = sys.argv[1]

try:
    # Use rugcheck.xyz API
    r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{token}/report", timeout=15)
    
    if r.status_code == 200:
        data = r.json()
        
        # Extract key metrics
        score = data.get("score", "N/A")
        risks = data.get("risks", [])
        
        # Determine risk level
        if isinstance(score, (int, float)):
            if score >= 800:
                level = "🟢 GOOD"
            elif score >= 500:
                level = "🟡 CAUTION"
            else:
                level = "🔴 RISKY"
        else:
            level = "⚪ UNKNOWN"
        
        print(f"""
{'='*40}
🔍 RUG CHECK REPORT
{'='*40}
Token: {token[:20]}...

📊 SCORE: {score}/1000 - {level}
{'='*40}""")
        
        if risks:
            print("⚠️ RISKS DETECTED:")
            for risk in risks[:5]:
                name = risk.get("name", "Unknown")
                desc = risk.get("description", "")[:50]
                lvl = risk.get("level", "info")
                emoji = "🔴" if lvl == "danger" else "🟡" if lvl == "warn" else "⚪"
                print(f"  {emoji} {name}")
        else:
            print("✅ No major risks detected")
            
    else:
        # Fallback - just show Dexscreener data
        r2 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=10)
        data = r2.json()
        pair = data.get("pairs", [{}])[0] if data.get("pairs") else {}
        liq = pair.get("liquidity", {}).get("usd", 0)
        
        if liq and float(liq) < 10000:
            print("🔴 WARNING: Low liquidity - possible rug risk")
        elif liq and float(liq) < 50000:
            print("🟡 CAUTION: Medium liquidity")
        else:
            print("🟢 Liquidity looks healthy")
            
except Exception as e:
    print(f"ERROR checking rug status: {e}")
