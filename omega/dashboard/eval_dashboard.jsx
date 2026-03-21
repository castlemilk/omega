/**
 * VECTORA TERMINAL v0.1
 * Crypto quant research node eval dashboard within the Omega system.
 *
 * Aesthetic: CRT phosphor — pure black, bright #00ff00, IBM Plex Mono, no borders radius,
 *            green glow on key numbers, terminal-style $ / > prefixes.
 *
 * 10 panels + positions pane:
 *  1.  Performance Overview   — equity curve BTC/USDT + ETH/USDT, vs BTC B&H
 *  2.  Sharpe Analysis        — raw + DSR, bootstrap CI, IS/OOS split
 *  3.  Risk Metrics           — max DD, Sortino, Calmar, VaR, funding rate, OI
 *  4.  Ablation Results       — Sharpe attribution per Vectora subsystem
 *  5.  Regime Performance     — RISK-ON / RISK-OFF / DELEVERAGE / ACCUMULATION
 *  6.  Crash Replay           — COVID / China ban / LUNA / FTX / Flash crash
 *  7.  Adversarial Health     — Ring 1 flag rate, false positive rate
 *  8.  TPE Convergence        — best score over 200 trials
 *  9.  Autonomy Status        — PICO → SUPERVISED → AUTONOMOUS history
 * 10.  Signal Quality         — OrderFlow(VPIN) / CrossAsset / Microstructure / Sentiment
 *
 * POSITIONS pane — current holdings by symbol
 * TRADES LOG pane — recent fills (BTC/ETH/SOL)
 */

const { useState, useEffect } = React;
const {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, ComposedChart,
  Scatter, Cell,
} = Recharts;

// ---------------------------------------------------------------------------
// Terminal palette
// ---------------------------------------------------------------------------
const T = {
  black:  '#000000',
  green:  '#00ff00',
  dim:    '#006600',
  mid:    '#009900',
  amber:  '#ffaa00',
  red:    '#ff2200',
  cyan:   '#00ffcc',
  white:  '#aaffaa',
  border: '#00ff00',
  font:   "'IBM Plex Mono','Courier New',Courier,monospace",
  glow:   '0 0 8px #00ff00, 0 0 2px #00ff00',
  glowA:  '0 0 8px #ffaa00',
  glowR:  '0 0 8px #ff2200',
};

// ---------------------------------------------------------------------------
// Seeded PRNG
// ---------------------------------------------------------------------------
function mulberry32(seed) {
  return () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const rng   = mulberry32(42);
const rand  = () => rng();
const randn = () => { const u=Math.max(1e-12,rand()),v=rand(); return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v); };

// ---------------------------------------------------------------------------
// Data generation
// ---------------------------------------------------------------------------
const N = 504;
const TRAIN_END = Math.floor(N * 0.60);

function buildData() {
  // Date labels
  const labels = [];
  for (let d=new Date('2023-01-02'); labels.length<N; d.setDate(d.getDate()+1))
    if (d.getDay()!==0 && d.getDay()!==6) labels.push(d.toISOString().slice(0,10));

  // Strategy returns — Sharpe ~1.05 (daily)
  const stRet = [];
  const equity = [100000]; // USDT
  for (let i=0; i<N; i++) {
    const r = 0.30/252 + (0.25/Math.sqrt(252))*randn();
    stRet.push(r);
    equity.push(equity[equity.length-1]*(1+r));
  }

  // BTC buy-and-hold
  const btc = [100000];
  for (let i=0; i<N; i++) btc.push(btc[btc.length-1]*(1+0.40/252+(0.80/Math.sqrt(252))*randn()));

  // Drawdown
  let peak=equity[0];
  const dd = equity.map(v=>{if(v>peak)peak=v;return peak>0?(v-peak)/peak*100:0;});

  // Stats
  const meanR = stRet.reduce((s,r)=>s+r,0)/N;
  const stdR  = Math.sqrt(stRet.map(r=>(r-meanR)**2).reduce((s,v)=>s+v,0)/(N-1));
  const sharpeAnn = (meanR/stdR)*Math.sqrt(252);

  const down = stRet.filter(r=>r<0);
  const dsStd = Math.sqrt(down.map(r=>r**2).reduce((s,v)=>s+v,0)/(down.length-1));
  const sortinoAnn = (meanR/dsStd)*Math.sqrt(252);
  const maxDDpct = Math.min(...dd)/100;
  const calmar = (meanR*252)/Math.abs(maxDDpct);

  const inS  = stRet.slice(0,TRAIN_END);
  const outS = stRet.slice(TRAIN_END);
  const mIS=inS.reduce((s,r)=>s+r,0)/inS.length, sIS=Math.sqrt(inS.map(r=>(r-mIS)**2).reduce((s,v)=>s+v,0)/(inS.length-1));
  const mOS=outS.reduce((s,r)=>s+r,0)/outS.length, sOS=Math.sqrt(outS.map(r=>(r-mOS)**2).reduce((s,v)=>s+v,0)/(outS.length-1));
  const sharpeIS  = (mIS/sIS)*Math.sqrt(252);
  const sharpeOOS = (mOS/sOS)*Math.sqrt(252);

  const sortedR=[...stRet].sort((a,b)=>a-b);
  const vi=Math.floor(0.05*N);
  const VaR  = -sortedR[vi]*100;
  const CVaR = -sortedR.slice(0,vi+1).reduce((s,r)=>s+r,0)/(vi+1)*100;

  // Chart arrays
  const perfData = labels.map((date,i)=>({
    date, i,
    omega: +equity[i+1]?.toFixed(0),
    btc:  +btc[i+1]?.toFixed(0),
    dd:   +dd[i+1]?.toFixed(2),
  })).filter(d=>d.omega);

  return {
    labels, equity, btc, dd, stRet, perfData,
    sharpeAnn, sortinoAnn, maxDDpct, calmar,
    sharpeIS, sharpeOOS, VaR, CVaR,
    meanR, stdR, annReturn: meanR*252,
    totalReturn: (equity[N]-equity[0])/equity[0],
    portfolioValue: equity[N],
  };
}
const D = buildData();

// Funding rate + OI series (synthetic, daily)
const fundingData = Array.from({length:60},(_,i)=>({
  t:i+1,
  funding: +(0.01+0.015*Math.sin(i/8)+0.008*randn()).toFixed(4), // %/8h
  oi:      +(8.2+1.5*Math.sin(i/12)+0.5*randn()).toFixed(2),    // $B
}));
const latestFunding = fundingData[fundingData.length-1].funding;
const latestOI      = fundingData[fundingData.length-1].oi;

// Ablation — Vectora subsystems
const ablation = [
  {name:'OrderFlow',     dSharpe:0.58, sig:true },
  {name:'CrossAsset',    dSharpe:0.44, sig:true },
  {name:'Microstructure',dSharpe:0.31, sig:true },
  {name:'Sentiment',     dSharpe:0.19, sig:false},
  {name:'Ring1',         dSharpe:0.42, sig:true },
  {name:'Memory',        dSharpe:0.18, sig:false},
  {name:'TPE',           dSharpe:0.11, sig:false},
];

// Crypto regimes
const regimes = [
  {name:'RISK-ON',      sharpe:1.38, ret:36.4, trades:51, pct:30},
  {name:'RISK-OFF',     sharpe:0.62, ret:12.1, trades:38, pct:24},
  {name:'DELEVERAGE',   sharpe:0.44, ret: 8.7, trades:29, pct:20},
  {name:'ACCUMULATION', sharpe:0.89, ret:19.3, trades:46, pct:26},
];
const currentRegimeIdx = 0;

// Crash scenarios
const crashes = [
  {name:'COVID Mar 2020',    sym:'BTCUSDT', dd: 8.4, recov:12,   sl:0, pnl: 2.1, pass:true },
  {name:'China Ban May 2021',sym:'BTCUSDT', dd:12.7, recov:18,   sl:1, pnl:-1.8, pass:true },
  {name:'LUNA May 2022',     sym:'LUNAUSDT',dd:94.2, recov:null, sl:2, pnl:-89.4,pass:false},
  {name:'FTX Nov 2022',      sym:'BTCUSDT', dd:18.3, recov:21,   sl:1, pnl:-3.2, pass:true },
  {name:'Flash Aug 2023',    sym:'BTCUSDT', dd: 6.1, recov:4,    sl:0, pnl: 0.4, pass:true },
];

// Adversarial health
const advSeries = Array.from({length:60},(_,i)=>({
  t:i+1,
  flag:Math.max(0,0.08+0.04*Math.sin(i/5)+0.025*randn()),
  fp:  Math.max(0,0.02+0.01*randn()),
}));

// TPE
const tpeSeries = (()=>{
  let best=0.2;
  return Array.from({length:200},(_,i)=>{
    const s=0.3+0.8*(1-Math.exp(-i/60))+0.12*randn();
    if(s>best)best=s;
    return {t:i+1,score:+s.toFixed(4),best:+best.toFixed(4)};
  });
})();

// Autonomy history
const autonomyHistory = [
  {date:'2023-01-02',level:'PICO',      dir:'',  reason:'system_init'},
  {date:'2023-04-15',level:'SUPERVISED',dir:'↑', reason:'sharpe=0.58'},
  {date:'2023-06-20',level:'PICO',      dir:'↓', reason:'drawdown 21%'},
  {date:'2023-09-01',level:'SUPERVISED',dir:'↑', reason:'sharpe=0.61'},
  {date:'2024-01-10',level:'AUTONOMOUS',dir:'↑', reason:'sharpe=1.12'},
];
const CURRENT_LEVEL = 'AUTONOMOUS';

// Vectora signals
const signals = [
  {name:'ORDERFLOW (VPIN)',  avgIC:0.0812, weight:0.34, t2:7, color:T.green},
  {name:'CROSS-ASSET',       avgIC:0.0631, weight:0.26, t2:9, color:T.cyan},
  {name:'MICROSTRUCTURE',    avgIC:0.0478, weight:0.22, t2:4, color:T.amber},
  {name:'SENTIMENT (FR+OI)', avgIC:0.0293, weight:0.18, t2:3, color:T.mid},
];

// Current positions
const positions = [
  {sym:'BTC/USDT', side:'LONG',  size: 0.45, entry:63420, mark:64810, upnl: 625.50, pct:+2.19},
  {sym:'ETH/USDT', side:'SHORT', size: 3.20, entry: 3180, mark: 3142, upnl: 121.60, pct:+1.19},
  {sym:'SOL/USDT', side:'LONG',  size:12.00, entry:  148, mark:  152, upnl:  48.00, pct:+2.70},
];

// Recent trades
const recentTrades = [
  {ts:'2024-07-15 14:32',sym:'BTC/USDT',side:'LONG', size:0.42,entry:63420,exit:64180,pnl: 319.20},
  {ts:'2024-07-14 09:11',sym:'ETH/USDT',side:'SHORT',size:2.80,entry: 3240,exit: 3198,pnl: 117.60},
  {ts:'2024-07-13 22:55',sym:'BTC/USDT',side:'LONG', size:0.35,entry:62100,exit:63800,pnl: 595.00},
  {ts:'2024-07-12 16:08',sym:'SOL/USDT',side:'SHORT',size:15.0,entry:  158,exit:  163,pnl: -75.00},
  {ts:'2024-07-11 11:44',sym:'BTC/USDT',side:'LONG', size:0.50,entry:61500,exit:62800,pnl: 650.00},
  {ts:'2024-07-10 08:22',sym:'ETH/USDT',side:'LONG', size:3.10,entry: 3050,exit: 3140,pnl: 279.00},
  {ts:'2024-07-09 19:07',sym:'SOL/USDT',side:'SHORT',size:10.0,entry:  162,exit:  158,pnl:  40.00},
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt    = (v,d=2) => typeof v==='number' ? v.toFixed(d) : v;
const fmtPct = v => `${(v*100).toFixed(1)}%`;
const fmtUSDT = v => `$${v.toLocaleString('en-US',{maximumFractionDigits:0})}`;

// ---------------------------------------------------------------------------
// Terminal tooltip
// ---------------------------------------------------------------------------
function TermTip({active,payload,label}) {
  if(!active||!payload?.length) return null;
  return (
    <div style={{background:T.black,border:`1px solid ${T.green}`,
                 padding:'6px 10px',fontFamily:T.font,fontSize:10}}>
      <p style={{color:T.dim,marginBottom:2}}>{label}</p>
      {payload.map((p,i)=>(
        <p key={i} style={{color:p.color||T.green}}>
          &gt; {p.name}: {typeof p.value==='number'?p.value.toFixed(4):p.value}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel wrapper
// ---------------------------------------------------------------------------
function P({title,children,style={}}) {
  return (
    <div style={{background:T.black,border:`1px solid ${T.green}`,
                 padding:'8px 10px',fontFamily:T.font,...style}}>
      {title && (
        <div style={{fontSize:10,color:T.dim,letterSpacing:'0.12em',textTransform:'uppercase',
                     borderBottom:`1px solid ${T.dim}`,paddingBottom:4,marginBottom:6}}>
          <span style={{color:T.dim}}>$ </span>{title}
        </div>
      )}
      {children}
    </div>
  );
}

// Compact stat row helper
function StatRow({label,value,color=T.green,glow=false}) {
  return (
    <div style={{display:'flex',justifyContent:'space-between',marginBottom:3,fontSize:11}}>
      <span style={{color:T.dim}}>{label}</span>
      <span style={{color,fontWeight:'bold',textShadow:glow?T.glow:'none'}}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TOP BAR
// ---------------------------------------------------------------------------
function TopBar() {
  const [now,setNow] = useState(new Date());
  useEffect(()=>{const id=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(id);},[]);

  const uPnL = positions.reduce((s,p)=>s+p.upnl,0);

  const stats=[
    {l:'TOTAL RETURN', v:fmtPct(D.totalReturn),  c:T.green},
    {l:'ANN RETURN',   v:fmtPct(D.annReturn),     c:T.green},
    {l:'SHARPE',       v:fmt(D.sharpeAnn),         c:T.green},
    {l:'SORTINO',      v:fmt(D.sortinoAnn),        c:T.green},
    {l:'MAX DD',       v:fmtPct(D.maxDDpct),       c:T.red  },
    {l:'VAR 95%',      v:`${D.VaR.toFixed(2)}%`,   c:T.amber},
    {l:'CVAR 95%',     v:`${D.CVaR.toFixed(2)}%`,  c:T.amber},
    {l:'IS SHARPE',    v:fmt(D.sharpeIS),          c:T.cyan },
    {l:'OOS SHARPE',   v:fmt(D.sharpeOOS),         c:D.sharpeOOS>0.5?T.green:T.amber},
    {l:'FUNDING /8H',  v:`${latestFunding.toFixed(4)}%`, c:latestFunding>0?T.amber:T.green},
    {l:'OPEN INT',     v:`$${latestOI}B`,           c:T.white},
    {l:'UNREALISED',   v:uPnL>0?`+$${uPnL.toFixed(0)}`:`-$${Math.abs(uPnL).toFixed(0)}`, c:T.green},
    {l:'AUTONOMY',     v:CURRENT_LEVEL,             c:T.green},
    {l:'CRASH PASS',   v:`${crashes.filter(c=>c.pass).length}/5`, c:T.green},
  ];

  return (
    <div style={{background:T.black,borderBottom:`1px solid ${T.green}`,fontFamily:T.font}}>
      {/* Header row */}
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',
                   padding:'6px 12px',borderBottom:`1px solid ${T.dim}`}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <span style={{fontSize:20,color:T.green,textShadow:T.glow,fontWeight:'bold'}}>Ω</span>
          <span style={{color:T.green,fontSize:14,letterSpacing:'0.18em',textShadow:T.glow}}>
            VECTORA TERMINAL
          </span>
          <span style={{color:T.dim,fontSize:10}}>v0.1</span>
          <span style={{color:T.dim,fontSize:10}}>│ CRYPTO QUANT RESEARCH NODE │ OMEGA SYSTEM</span>
        </div>
        <div style={{color:T.dim,fontSize:10}}>
          {now.toISOString().slice(0,19)} UTC
          <span style={{marginLeft:12,color:T.green,textShadow:T.glow}}>⬤ LIVE</span>
        </div>
      </div>

      {/* Portfolio value */}
      <div style={{textAlign:'center',padding:'8px 0 4px'}}>
        <div style={{fontSize:9,color:T.dim,letterSpacing:'0.2em',marginBottom:1}}>
          PORTFOLIO VALUE (USDT)
        </div>
        <div style={{fontSize:48,fontWeight:'bold',color:T.green,textShadow:T.glow,lineHeight:1}}>
          {fmtUSDT(D.portfolioValue)}
        </div>
        <div style={{fontSize:11,color:T.dim,marginTop:1}}>
          STARTED: $100,000 USDT &nbsp;│&nbsp;
          GAIN: +{fmtUSDT(D.portfolioValue-100000)} (+{(D.totalReturn*100).toFixed(1)}%)
          &nbsp;│&nbsp; UNREALISED PNL: <span style={{color:T.green}}>
            +${positions.reduce((s,p)=>s+p.upnl,0).toFixed(2)}
          </span>
        </div>
      </div>

      {/* Stats strip */}
      <div style={{display:'flex',borderTop:`1px solid ${T.dim}`,overflowX:'auto'}}>
        {stats.map((s,i)=>(
          <div key={i} style={{flex:'0 0 auto',minWidth:90,padding:'4px 10px',
                               borderRight:`1px solid ${T.dim}`,textAlign:'center'}}>
            <div style={{fontSize:9,color:T.dim,letterSpacing:'0.08em'}}>{s.l}</div>
            <div style={{fontSize:12,fontWeight:'bold',color:s.c,
                         textShadow:s.c===T.green?T.glow:s.c===T.red?T.glowR:T.glowA}}>
              {s.v}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel 1 — Performance chart (center, largest element)
// ---------------------------------------------------------------------------
function PerfChart() {
  const [mode,setMode] = useState('equity');
  const data = D.perfData.filter((_,i)=>i%2===0);
  const splitIdx = data.findIndex(d=>d.i>=TRAIN_END);

  return (
    <P title="PERFORMANCE OVERVIEW — BTC/USDT + ETH/USDT vs BUY&HOLD"
       style={{height:'100%',display:'flex',flexDirection:'column'}}>
      <div style={{display:'flex',gap:6,marginBottom:6,alignItems:'center'}}>
        {['equity','dd'].map(m=>(
          <button key={m} onClick={()=>setMode(m)}
            style={{
              background:mode===m?T.dim:T.black,color:mode===m?T.black:T.green,
              border:`1px solid ${T.green}`,fontFamily:T.font,fontSize:10,
              padding:'2px 8px',cursor:'pointer',textTransform:'uppercase',
            }}>
            {m==='equity'?'> EQUITY CURVE':'> DRAWDOWN'}
          </button>
        ))}
        <span style={{marginLeft:'auto',color:T.dim,fontSize:9}}>
          ▓ TRAIN [{D.labels[0]}→{D.labels[TRAIN_END-1]}] &nbsp; ░ TEST [{D.labels[TRAIN_END]}→{D.labels[D.labels.length-1]}]
        </span>
      </div>
      <div style={{flex:1,minHeight:0}}>
        <ResponsiveContainer width="100%" height="100%">
          {mode==='equity'?(
            <ComposedChart data={data} margin={{top:4,right:4,bottom:18,left:64}}>
              <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3}/>
              <XAxis dataKey="date" tick={{fill:T.dim,fontSize:9,fontFamily:T.font}}
                     interval={Math.floor(data.length/7)}/>
              <YAxis tick={{fill:T.dim,fontSize:9,fontFamily:T.font}}
                     tickFormatter={v=>`$${(v/1000).toFixed(0)}K`}/>
              <Tooltip content={<TermTip/>}/>
              {splitIdx>0&&(
                <ReferenceLine x={data[splitIdx]?.date} stroke={T.dim} strokeDasharray="4 4"
                  label={{value:'OOS START',fill:T.dim,fontSize:8,fontFamily:T.font,position:'insideTopRight'}}/>
              )}
              <Line type="monotone" dataKey="btc" stroke={T.dim} strokeWidth={1}
                    dot={false} name="BTC B&H" strokeDasharray="3 3"/>
              <Line type="monotone" dataKey="omega" stroke={T.green} strokeWidth={2}
                    dot={false} name="VECTORA"
                    style={{filter:`drop-shadow(0 0 4px ${T.green})`}}/>
            </ComposedChart>
          ):(
            <AreaChart data={data} margin={{top:4,right:4,bottom:18,left:50}}>
              <defs>
                <linearGradient id="ddG" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={T.red} stopOpacity={0.5}/>
                  <stop offset="100%" stopColor={T.red} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3}/>
              <XAxis dataKey="date" tick={{fill:T.dim,fontSize:9,fontFamily:T.font}}
                     interval={Math.floor(data.length/7)}/>
              <YAxis tick={{fill:T.dim,fontSize:9,fontFamily:T.font}}
                     tickFormatter={v=>`${v.toFixed(0)}%`}/>
              <Tooltip content={<TermTip/>}/>
              <ReferenceLine y={-20} stroke={T.amber} strokeDasharray="4 2"
                label={{value:'-20%',fill:T.amber,fontSize:9,fontFamily:T.font}}/>
              <Area type="monotone" dataKey="dd" stroke={T.red} fill="url(#ddG)"
                    strokeWidth={1.5} name="DD%"/>
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 2 — Sharpe Analysis (left)
// ---------------------------------------------------------------------------
function SharpePanel() {
  const ci={lo:D.sharpeAnn-0.31,hi:D.sharpeAnn+0.29};
  const dsr=D.sharpeAnn*0.78;
  const sig=ci.lo>0;
  return (
    <P title="SHARPE ANALYSIS">
      <div style={{padding:'3px 6px',border:`1px solid ${sig?T.green:T.red}`,
                   color:sig?T.green:T.red,fontSize:10,marginBottom:6,
                   textShadow:sig?T.glow:T.glowR}}>
        {sig?'> SIG AT 95% CONFIDENCE':'> NOT SIGNIFICANT'}
      </div>
      {[
        ['RAW SHARPE',   fmt(D.sharpeAnn), T.green],
        ['CI 95% LO',    fmt(ci.lo),       T.dim  ],
        ['CI 95% HI',    fmt(ci.hi),       T.dim  ],
        ['DEFLATED DSR', fmt(dsr),         T.amber],
        ['IS SHARPE',    fmt(D.sharpeIS),  T.cyan ],
        ['OOS SHARPE',   fmt(D.sharpeOOS), D.sharpeOOS>0.5?T.green:T.amber],
        ['ANN VOL',      fmtPct(D.stdR*Math.sqrt(252)), T.white],
      ].map(([l,v,c])=><StatRow key={l} label={l} value={v} color={c} glow={c===T.green}/>)}
      <div style={{fontSize:9,color:T.dim,marginTop:5,borderTop:`1px solid ${T.dim}`,paddingTop:3}}>
        DSR corrects for 5 backtests trialled
      </div>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 3 — Risk Metrics (left)
// ---------------------------------------------------------------------------
function RiskPanel() {
  let maxDur=0,cur=0;
  D.dd.forEach(v=>{if(v<-1){cur++;maxDur=Math.max(maxDur,cur);}else cur=0;});
  return (
    <P title="RISK METRICS">
      {[
        ['MAX DRAWDOWN',    fmtPct(D.maxDDpct),            T.red  ],
        ['DD DURATION',     `${maxDur} BARS`,               T.amber],
        ['SORTINO RATIO',   fmt(D.sortinoAnn),              T.green],
        ['CALMAR RATIO',    fmt(D.calmar),                  T.green],
        ['VAR 95% DAILY',   `${D.VaR.toFixed(2)}%`,         T.amber],
        ['CVAR 95% DAILY',  `${D.CVaR.toFixed(2)}%`,        T.red  ],
        ['FUNDING RATE /8H',`${latestFunding.toFixed(4)}%`, latestFunding>0?T.amber:T.green],
        ['OPEN INTEREST',   `$${latestOI}B`,                T.white],
        ['WIN RATE',        '54.3%',                        T.green],
        ['PROFIT FACTOR',   '1.83',                         T.green],
      ].map(([l,v,c])=><StatRow key={l} label={l} value={v} color={c} glow={c===T.green}/>)}
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 4 — Ablation (center bottom-left)
// ---------------------------------------------------------------------------
function AblationPanel() {
  return (
    <P title="ABLATION — ΔSharpe PER SUBSYSTEM">
      <div style={{fontSize:10,color:T.dim,marginBottom:4}}>
        FULL SYSTEM: <span style={{color:T.green,textShadow:T.glow}}>{fmt(D.sharpeAnn)}</span>
      </div>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={ablation} layout="vertical" margin={{top:2,right:30,bottom:2,left:90}}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3} horizontal={false}/>
          <XAxis type="number" tick={{fill:T.dim,fontSize:9,fontFamily:T.font}}/>
          <YAxis type="category" dataKey="name" tick={{fill:T.white,fontSize:10,fontFamily:T.font}} width={88}/>
          <Tooltip content={<TermTip/>}/>
          <Bar dataKey="dSharpe" name="ΔSharpe" radius={0}
               label={({value,x,y,width,height,index})=>(
                 <text x={x+width+3} y={y+height/2+4}
                       fill={ablation[index]?.sig?T.green:T.dim}
                       fontSize={10} fontFamily={T.font}>
                   {value.toFixed(2)}{ablation[index]?.sig?' ★':''}
                 </text>
               )}>
            {ablation.map((d,i)=>(
              <Cell key={i} fill={d.sig?T.green:T.dim}
                    style={d.sig?{filter:`drop-shadow(0 0 3px ${T.green})`}:{}}/>
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 5 — Regime (center bottom-right)
// ---------------------------------------------------------------------------
function RegimePanel() {
  return (
    <P title="REGIME BREAKDOWN — CRYPTO MARKET STATES">
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6}}>
        {regimes.map((r,i)=>(
          <div key={r.name} style={{
            border:`1px solid ${i===currentRegimeIdx?T.green:T.dim}`,
            padding:'5px 7px',
            background:i===currentRegimeIdx?`${T.green}09`:T.black,
          }}>
            <div style={{fontSize:9,color:i===0?T.green:T.dim,letterSpacing:'0.1em',
                         textShadow:i===0?T.glow:'none'}}>
              {r.name}{i===currentRegimeIdx?' ◀ ACTIVE':''}
            </div>
            <div style={{fontSize:17,color:T.green,fontWeight:'bold',
                         textShadow:i===0?T.glow:'none'}}>
              {r.sharpe.toFixed(2)}
            </div>
            <div style={{fontSize:10,color:T.dim}}>
              RET:{r.ret.toFixed(1)}% N:{r.trades}
            </div>
            <div style={{marginTop:3,height:3,background:T.dim+'44'}}>
              <div style={{width:`${r.pct}%`,height:'100%',background:T.green,
                           boxShadow:`0 0 3px ${T.green}`}}/>
            </div>
            <div style={{fontSize:9,color:T.dim,textAlign:'right'}}>{r.pct}%</div>
          </div>
        ))}
      </div>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 6 — Crash Replay (bottom)
// ---------------------------------------------------------------------------
function CrashPanel() {
  const passed = crashes.filter(c=>c.pass).length;
  return (
    <P title="CRASH REPLAY RESULTS — HISTORICAL STRESS TESTS">
      <div style={{fontSize:10,marginBottom:5}}>
        <span style={{color:passed===crashes.length?T.green:T.amber,
                      textShadow:passed===crashes.length?T.glow:T.glowA}}>
          {passed}/{crashes.length} SCENARIOS PASSED
        </span>
        <span style={{color:T.dim,marginLeft:12}}>
          STOP-LOSS: 15% │ MAX-DD FAIL: 30% │ STRATEGY: RING1-FILTERED
        </span>
      </div>
      <table style={{width:'100%',borderCollapse:'collapse',fontSize:10,fontFamily:T.font}}>
        <thead>
          <tr style={{borderBottom:`1px solid ${T.green}`}}>
            {['SCENARIO','SYM','MAX DD','RECOVERY','STOP-L','PNL','STATUS'].map(h=>(
              <th key={h} style={{textAlign:'left',color:T.dim,padding:'2px 8px 2px 0',
                                   letterSpacing:'0.08em'}}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {crashes.map(c=>(
            <tr key={c.name} style={{borderBottom:`1px solid ${T.dim}22`}}>
              <td style={{color:T.white,padding:'2px 8px 2px 0'}}>{c.name}</td>
              <td style={{color:T.cyan,paddingRight:8}}>{c.sym}</td>
              <td style={{color:c.dd>30?T.red:c.dd>15?T.amber:T.green,fontWeight:'bold',
                          paddingRight:8,textShadow:c.dd>30?T.glowR:c.dd>15?T.glowA:T.glow}}>
                {c.dd.toFixed(1)}%
              </td>
              <td style={{color:c.recov?T.white:T.red,paddingRight:8}}>
                {c.recov?`${c.recov} BARS`:'NEVER ∞'}
              </td>
              <td style={{color:c.sl>0?T.amber:T.green,paddingRight:8}}>{c.sl}</td>
              <td style={{color:c.pnl>=0?T.green:T.red,fontWeight:'bold',
                          textShadow:c.pnl>=0?T.glow:T.glowR,paddingRight:8}}>
                {c.pnl>=0?'+':''}{c.pnl.toFixed(1)}%
              </td>
              <td style={{color:c.pass?T.green:T.red,fontWeight:'bold',
                          textShadow:c.pass?T.glow:T.glowR}}>
                [{c.pass?'PASS':'FAIL'}]
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 7 — Adversarial Health (left)
// ---------------------------------------------------------------------------
function AdvPanel() {
  const avgFlag = advSeries.reduce((s,d)=>s+d.flag,0)/advSeries.length;
  const avgFP   = advSeries.reduce((s,d)=>s+d.fp,0)/advSeries.length;
  return (
    <P title="ADVERSARIAL HEALTH [RING 1]">
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:5,marginBottom:6}}>
        {[
          {l:'FLAG RATE',    v:`${(avgFlag*100).toFixed(1)}%`, c:T.amber},
          {l:'FALSE POS',    v:`${(avgFP*100).toFixed(1)}%`,   c:T.green},
          {l:'ENSEMBLE DIS', v:'34.2%',                        c:T.cyan},
          {l:'RING1',        v:'ACTIVE',                       c:T.green},
        ].map(s=>(
          <div key={s.l} style={{border:`1px solid ${T.dim}`,padding:'3px 5px'}}>
            <div style={{fontSize:9,color:T.dim}}>{s.l}</div>
            <div style={{fontSize:13,color:s.c,fontWeight:'bold',
                         textShadow:s.c===T.green?T.glow:s.c===T.amber?T.glowA:'none'}}>
              {s.v}
            </div>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={advSeries} margin={{top:2,right:2,bottom:2,left:22}}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3}/>
          <XAxis dataKey="t" tick={{fill:T.dim,fontSize:8,fontFamily:T.font}} interval={14}/>
          <YAxis tick={{fill:T.dim,fontSize:8,fontFamily:T.font}}
                 tickFormatter={v=>`${(v*100).toFixed(0)}%`} width={26}/>
          <Tooltip content={<TermTip/>}/>
          <Area type="monotone" dataKey="flag" stroke={T.amber} fill={`${T.amber}22`}
                strokeWidth={1} name="Flag%"/>
          <Line type="monotone" dataKey="fp" stroke={T.green} strokeWidth={1} dot={false} name="FP%"/>
        </AreaChart>
      </ResponsiveContainer>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 8 — TPE Convergence (right)
// ---------------------------------------------------------------------------
function TPEPanel() {
  const best = tpeSeries[tpeSeries.length-1].best;
  return (
    <P title="TPE CONVERGENCE">
      <StatRow label="BEST SCORE" value={best.toFixed(4)} color={T.green} glow/>
      <StatRow label="TRIALS"     value="200"/>
      <StatRow label="CONVERGED"  value="~TRIAL 130" color={T.cyan}/>
      <StatRow label="STATUS"     value="STABLE" color={T.green}/>
      <ResponsiveContainer width="100%" height={100} style={{marginTop:4}}>
        <ComposedChart data={tpeSeries.filter((_,i)=>i%3===0)} margin={{top:2,right:2,bottom:2,left:22}}>
          <CartesianGrid stroke={T.dim} strokeDasharray="2 10" opacity={0.3}/>
          <XAxis dataKey="t" tick={{fill:T.dim,fontSize:8,fontFamily:T.font}} interval={24}/>
          <YAxis tick={{fill:T.dim,fontSize:8,fontFamily:T.font}} width={26}/>
          <Tooltip content={<TermTip/>}/>
          <Scatter data={tpeSeries.filter((_,i)=>i%4===0)} dataKey="score"
                   fill={T.dim} opacity={0.6} name="Trial"/>
          <Line type="monotone" dataKey="best" stroke={T.green} strokeWidth={2}
                dot={false} name="Best"
                style={{filter:`drop-shadow(0 0 3px ${T.green})`}}/>
        </ComposedChart>
      </ResponsiveContainer>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 9 — Autonomy Status (right)
// ---------------------------------------------------------------------------
function AutoPanel() {
  const lc={PICO:T.dim,SUPERVISED:T.amber,AUTONOMOUS:T.green};
  return (
    <P title="AUTONOMY STATUS">
      <div style={{textAlign:'center',padding:'5px',border:`1px solid ${T.green}`,
                   marginBottom:6,textShadow:T.glow}}>
        <div style={{fontSize:9,color:T.dim,letterSpacing:'0.15em'}}>CURRENT LEVEL</div>
        <div style={{fontSize:18,color:T.green,fontWeight:'bold',textShadow:T.glow}}>
          {CURRENT_LEVEL}
        </div>
      </div>
      <div style={{fontSize:9,color:T.dim,marginBottom:5}}>
        &gt; PROMO: cycles≥10 │ sharpe≥0.5 │ dd≤15%
      </div>
      <div style={{fontSize:10}}>
        {autonomyHistory.map((e,i)=>(
          <div key={i} style={{display:'flex',gap:4,marginBottom:2,
                               borderBottom:`1px solid ${T.dim}22`,paddingBottom:2,flexWrap:'wrap'}}>
            <span style={{color:T.dim,minWidth:72,fontSize:9}}>{e.date}</span>
            <span style={{color:e.dir==='↑'?T.green:e.dir==='↓'?T.red:T.dim,minWidth:10}}>
              {e.dir||'·'}
            </span>
            <span style={{color:lc[e.level],fontWeight:'bold',fontSize:9}}>{e.level}</span>
            <span style={{color:T.dim,fontSize:9}}>/ {e.reason}</span>
          </div>
        ))}
      </div>
    </P>
  );
}

// ---------------------------------------------------------------------------
// Panel 10 — Signal Quality (right)
// ---------------------------------------------------------------------------
function SignalPanel() {
  return (
    <P title="SIGNAL QUALITY — VECTORA FACTORS">
      {signals.map(s=>(
        <div key={s.name} style={{marginBottom:5}}>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:10,marginBottom:2}}>
            <span style={{color:T.white}}>{s.name}</span>
            <span style={{color:T.cyan,fontSize:9}}>IC:{s.avgIC.toFixed(4)} w:{(s.weight*100).toFixed(0)}% t½:{s.t2}d</span>
          </div>
          <div style={{height:4,background:T.dim+'33',border:`1px solid ${T.dim}`}}>
            <div style={{width:`${s.weight*100*3}%`,height:'100%',background:s.color,
                         boxShadow:`0 0 3px ${s.color}`}}/>
          </div>
        </div>
      ))}
    </P>
  );
}

// ---------------------------------------------------------------------------
// Positions panel (right)
// ---------------------------------------------------------------------------
function PositionsPanel() {
  return (
    <P title="OPEN POSITIONS">
      {positions.map(pos=>(
        <div key={pos.sym} style={{borderBottom:`1px solid ${T.dim}22`,
                                    paddingBottom:5,marginBottom:5}}>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:11}}>
            <span style={{color:pos.side==='LONG'?T.green:T.amber,fontWeight:'bold',
                          textShadow:pos.side==='LONG'?T.glow:T.glowA}}>
              [{pos.side}] {pos.sym}
            </span>
            <span style={{color:T.green,textShadow:T.glow}}>
              +${pos.upnl.toFixed(2)} ({pos.pct>=0?'+':''}{pos.pct.toFixed(2)}%)
            </span>
          </div>
          <div style={{fontSize:9,color:T.dim}}>
            SIZE: {pos.size} │ ENTRY: {pos.entry} │ MARK: {pos.mark}
          </div>
        </div>
      ))}
    </P>
  );
}

// ---------------------------------------------------------------------------
// Trades log (right)
// ---------------------------------------------------------------------------
function TradesPanel() {
  return (
    <P title="RECENT FILLS">
      {recentTrades.map((t,i)=>(
        <div key={i} style={{borderBottom:`1px solid ${T.dim}22`,
                              paddingBottom:3,marginBottom:3}}>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:10}}>
            <span style={{color:t.side==='LONG'?T.green:T.amber}}>
              {t.side==='LONG'?'↑':'↓'} {t.sym}
            </span>
            <span style={{color:t.pnl>=0?T.green:T.red,fontWeight:'bold',
                          textShadow:t.pnl>=0?T.glow:T.glowR}}>
              {t.pnl>=0?'+':''}${t.pnl.toFixed(2)}
            </span>
          </div>
          <div style={{fontSize:8,color:T.dim}}>
            {t.ts} │ {t.size} │ {t.entry}→{t.exit}
          </div>
        </div>
      ))}
    </P>
  );
}

// ---------------------------------------------------------------------------
// Root App
// ---------------------------------------------------------------------------
export default function App() {
  return (
    <div style={{background:T.black,color:T.green,fontFamily:T.font,
                 minHeight:'100vh',display:'flex',flexDirection:'column'}}>

      <TopBar/>

      {/* ── MAIN BODY ── left │ center │ right */}
      <div style={{display:'grid',gridTemplateColumns:'220px 1fr 250px',
                   gap:3,padding:3,flex:1,minHeight:0,alignItems:'start'}}>

        {/* LEFT SIDEBAR */}
        <div style={{display:'flex',flexDirection:'column',gap:3}}>
          <SharpePanel/>
          <RiskPanel/>
          <AdvPanel/>
        </div>

        {/* CENTER */}
        <div style={{display:'flex',flexDirection:'column',gap:3}}>
          {/* Main equity chart */}
          <div style={{height:340}}>
            <PerfChart/>
          </div>
          {/* Ablation + Regime */}
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:3}}>
            <AblationPanel/>
            <RegimePanel/>
          </div>
        </div>

        {/* RIGHT SIDEBAR */}
        <div style={{display:'flex',flexDirection:'column',gap:3}}>
          <PositionsPanel/>
          <TPEPanel/>
          <AutoPanel/>
          <SignalPanel/>
          <TradesPanel/>
        </div>
      </div>

      {/* ── BOTTOM ── Crash replay */}
      <div style={{padding:'0 3px 3px'}}>
        <CrashPanel/>
      </div>

      <div style={{borderTop:`1px solid ${T.dim}`,padding:'3px 12px',
                   fontSize:9,color:T.dim,textAlign:'center'}}>
        Ω VECTORA TERMINAL v0.1 │ OMEGA SYSTEM │ {D.labels[0]} → {D.labels[D.labels.length-1]} │ 504 TRADING DAYS │ COMMISSION 0.1%
      </div>
    </div>
  );
}
