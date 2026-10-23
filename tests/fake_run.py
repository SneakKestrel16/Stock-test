import sys, random, json, numpy as np, pandas as pd
from datetime import date, timedelta
from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stock_tracker as s
random.seed(3); np.random.seed(3)
def series(n, drift):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n, tz="America/New_York")
    r = np.random.normal(drift, 0.018, n); r[-5] = -0.07
    return pd.Series(100*np.exp(np.cumsum(r)), index=idx)
class FakeTicker:
    def __init__(s_, t): s_.t=t
    @property
    def info(s_):
        return {"shortName":s_.t+" Corp","sector":"Technology","currentPrice":random.uniform(50,400),
          "marketCap":random.uniform(5e9,2e12),"forwardPE":random.choice([-3,random.uniform(10,40)]),
          "priceToBook":random.uniform(1,20),"enterpriseToEbitda":random.uniform(6,30),
          "freeCashflow":random.choice([-1e9,random.uniform(1e9,5e10)]),"returnOnEquity":random.uniform(0,.6),
          "profitMargins":random.uniform(0,.35),"debtToEquity":random.uniform(0,300),
          "revenueGrowth":random.uniform(-.05,.4),"earningsGrowth":random.uniform(-.2,.6),
          "targetMeanPrice":random.uniform(60,450),"recommendationKey":"buy"}
    def history(s_, period="1y", auto_adjust=True):
        n={"3mo":63,"1y":252,"5y":1260}.get(period,1260); c=series(n,0.0006)
        df=pd.DataFrame({"Open":c,"High":c*1.01,"Low":c*.99,"Close":c,"Volume":1e6,"Dividends":0.0,"Stock Splits":0.0})
        df.iloc[-20, df.columns.get_loc("Dividends")]=0.83; return df
    @property
    def news(s_):
        return [{"id":"a1","content":{"title":f"{s_.t} unveils new product line","pubDate":str(date.today())+"T14:00:00Z",
                 "canonicalUrl":{"url":"https://example.com/a1"},"provider":{"displayName":"Reuters"}}},
                {"title":"Old-style item","link":"https://example.com/b","providerPublishTime":1761100000,"publisher":"Yahoo"}]
    @property
    def upgrades_downgrades(s_):
        i=pd.DatetimeIndex([pd.Timestamp.today()-pd.Timedelta(days=3),pd.Timestamp.today()-pd.Timedelta(days=90)],name="GradeDate")
        return pd.DataFrame({"Firm":["Morgan Stanley","UBS"],"ToGrade":["Underweight","Buy"],"FromGrade":["Equal-Weight",""],"Action":["down","init"]},index=i)
    @property
    def calendar(s_): return {"Earnings Date":[date.today()+timedelta(days=12)]}
    @property
    def fast_info(s_): return {"last_price": 100*random.uniform(0.8,1.25)}
def fake_download(tickers, start=None, auto_adjust=True, actions=False, **k):
    n=len(pd.bdate_range(start, pd.Timestamp.today())) if start is not None else 275
    idx=pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    close=pd.DataFrame({t:series(n, random.uniform(-0.0003,0.0009)).values for t in tickers},index=idx)
    out={"Close":close}
    if not auto_adjust: out["Adj Close"]=close*1.0
    if actions:
        sp=pd.DataFrame(0.0,index=idx,columns=tickers); sp.iloc[n//2,0]=2.0; out["Stock Splits"]=sp
    return pd.concat(out,axis=1)
s.yf.Ticker=FakeTicker; s.yf.download=fake_download
class R:
    status_code=200
    def __init__(s_, d): s_.d=d; s_.text=json.dumps(d)
    def raise_for_status(s_): pass
    def json(s_): return s_.d
def fake_get(url, headers=None, timeout=None):
    if "fred.stlouisfed.org" in url:
        r=R({}); days=pd.date_range(end=pd.Timestamp.today(), periods=200)
        r.text="observation_date,X\n"+"\n".join(f"{d:%Y-%m-%d},{random.uniform(-0.5,4):.2f}" for d in days)
        return r
    assert "@" in headers["User-Agent"]
    if "company_tickers" in url:
        return R({str(i):{"cik_str":789019 if t=="MSFT" else 1000+i,"ticker":t,"title":t}
                  for i,t in enumerate(s.DEFAULT_TICKERS)})
    if "companyfacts" in url: return R(fake_facts(int(url.split("CIK")[1][:10])))
    t=str(date.today()-timedelta(days=2))
    return R({"filings":{"recent":{"form":["8-K","4","4","10-Q","8-K"],"filingDate":[t,t,t,t,"2020-01-01"],
      "accessionNumber":["0001-26-1","0001-26-2","0001-26-3","0001-26-4","x"],"primaryDocument":["a.htm"]*5,
      "items":["5.02,9.01","","","","2.02"]}}})
def fake_facts(cik):
    g=random.Random(cik); rev0=g.uniform(2e10,2e11); gr=g.uniform(-0.02,0.15); m=g.uniform(-0.05,0.3)
    fy=lambda tag,f: {tag:{"units":{"USD":[{"start":f"{y}-01-01","end":f"{y}-12-31","val":f(y),
                      "filed":f"{y+1}-02-15","form":"10-K"} for y in range(2010,2026)]}}}
    q=lambda tag,v,unit="USD": {tag:{"units":{unit:[{"end":f"{y}-{mo}-30","val":v*g.uniform(.9,1.1),
                      "filed":f"{y}-{mo}-30" if mo=="03" else f"{y+(mo=='12')}-{'02' if mo=='12' else mo}-28",
                      "form":"10-Q"} for y in range(2010,2026) for mo in ("03","06","09","12")]}}}
    rev=lambda y: rev0*(1+gr)**(y-2010)
    gaap={**fy("Revenues",rev),**fy("NetIncomeLoss",lambda y: rev(y)*m*g.uniform(.7,1.3)),
          **fy("NetCashProvidedByUsedInOperatingActivities",lambda y: rev(y)*(m+.05)),
          **fy("PaymentsToAcquirePropertyPlantAndEquipment",lambda y: rev(y)*.04),
          **q("StockholdersEquity",rev0*g.uniform(.3,2)),**q("LongTermDebt",rev0*g.uniform(0,1.5))}
    return {"facts":{"us-gaap":gaap,"dei":q("EntityCommonStockSharesOutstanding",g.uniform(.5e9,3e9),"shares")}}
s.requests.get=fake_get
if __name__ == "__main__":
    sys.argv=["x"]+sys.argv[1:]; s.main()
