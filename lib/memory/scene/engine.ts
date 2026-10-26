// @ts-nocheck -- a verbatim port of the validated mockup (docs/Design/Memory-Cortex/index.html, the visual
// reference). Types arrive section by section as the surface is split into modules (MEMORY-SURFACE-BUILD.md §6);
// until then this file keeps the mockup's code exactly, so the look cannot drift in the port.
/* eslint-disable */
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { Delaunay } from 'd3-delaunay';
import { MEMORY_CSS, MEMORY_HTML } from './markup';

export interface MemoryEngineOptions {
  /** The memory model (the snapshot / API shape). Absent: the synthetic generator draws (development only). */
  data?: unknown;
  /** Called when WebGL2 is missing or the renderer cannot start. */
  onError?: (e: unknown) => void;
  /** The memory-native search (GET /api/memory/search). Absent: the engine searches its own model (the demo). */
  search?: (q: string, signal: AbortSignal) => Promise<any>;
  /** Read the model again (follow mode lost live messages: the model on screen is behind the store). */
  reload?: () => void;
  /** The Oracle view's record (GET /api/memory/oracle consumers: job, clauses, history, curve). Absent: the snapshot's. */
  oracle?: any[];
  /** Corrections v1 (POST /api/memory/correct, /undo, GET /corrections). Absent: no correction actions (the demo). */
  correct?: (action: "confirm" | "wrong" | "forget", target: string) => Promise<any>;
  undo?: (correctionId: string) => Promise<any>;
  corrections?: () => Promise<any>;
  /** Every turn a claim was given to IRIS (GET /api/memory/claims/<id>/uses). */
  uses?: (landmarkId: string) => Promise<any>;
  /** Corrections on pins and strands (pin / unpin / hold / release, forget_learned, purge). */
  correctTarget?: (action: string, target: string, extra?: Record<string, unknown>) => Promise<any>;
}

export interface MemoryEngine {
  /** Keys act only while the surface is the active one. */
  setActive(active: boolean): void;
  /** Fly to a thing: "claim:<id>", "strand:<id>", "thread:<id>", "turn:<conv>:<turn>", "lens:<name>". False: not in this memory. */
  focus(ref: string): boolean;
  /** A live tap message ({type, payload}: memory_event, landmark_update, oracle_decision); follow mode plays it. */
  live(msg: { type: string; payload?: any }): void;
  /** Memory is what the user looks at: keep full sharpness, give up frames instead. */
  setFocus(focused: boolean): void;
  /** The governor's state (development). */
  stats(): { pageFps: number; maxFps: number; dpr: number };
  /** Stop drawing (hidden, another surface, a closed dashboard); resume picks up without a time jump. */
  pause(): void;
  resume(): void;
  dispose(): void;
  /** The inspection handle (the mockup's window.__cortex). */
  debug: any;
}

export function createMemoryEngine(host: HTMLElement, opts: MemoryEngineOptions = {}): MemoryEngine {
host.classList.add('iris-memory');
host.innerHTML = `<style>${MEMORY_CSS}</style>${MEMORY_HTML}`;
// The page coupling of the mockup, re-pointed at the host box (the mockup's code below reads these names).
let innerWidth = host.clientWidth || 1, innerHeight = host.clientHeight || 1;
const _cleanups: Array<() => void> = [];
const _px = (e) => e.clientX - host.getBoundingClientRect().left;
const _py = (e) => e.clientY - host.getBoundingClientRect().top;
const addEventListener = (t, f, o?) => { window.addEventListener(t, f, o); _cleanups.push(() => window.removeEventListener(t, f, o)); };
const location = { search: '' };
const document = {
  getElementById: (id) => host.querySelector('#' + id),
  querySelector: (s) => host.querySelector(s),
  querySelectorAll: (s) => host.querySelectorAll(s),
  createElement: (t) => window.document.createElement(t),
  createElementNS: (n, t) => window.document.createElementNS(n, t),
  get activeElement() { return window.document.activeElement; },
  documentElement: host,
};
let _active = true;


const V3 = THREE.Vector3;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ═══════════════════════════════════════════════════════════════════════════
// 0. small utilities
// ═══════════════════════════════════════════════════════════════════════════
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
let rng = mulberry32(20261014);
const rand=(a=0,b=1)=>a+(b-a)*rng();
const randi=(a,b)=>Math.floor(rand(a,b+1));
const pick=a=>a[Math.floor(rng()*a.length)];
function gauss(){let u=0,v=0;while(!u)u=rng();while(!v)v=rng();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)}
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const lerp=(a,b,t)=>a+(b-a)*t;
const smooth01=t=>{t=clamp(t,0,1);return t*t*(3-2*t)};
const easeIO=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
const nowS=()=>Date.now()/1000;
function weighted(pairs){let s=0;for(const p of pairs)s+=p[1];let r=rng()*s;for(const p of pairs){r-=p[1];if(r<=0)return p[0]}return pairs[0][0]}
function fib(n,i){const y=1-(i+.5)/n*2,r=Math.sqrt(1-y*y),th=i*2.399963229728653;return new V3(Math.cos(th)*r,y,Math.sin(th)*r)}
function ago(ts){const d=Math.max(0,nowS()-ts);
  if(d<45)return 'just now'; if(d<3600)return Math.round(d/60)+' min ago';
  if(d<86400)return Math.round(d/3600)+' h ago'; if(d<86400*14)return Math.round(d/86400)+' days ago';
  if(d<86400*60)return Math.round(d/604800)+' weeks ago'; return Math.round(d/2592000)+' months ago'}
function span(s){s=Math.max(1,s); if(s<60)return Math.round(s)+' s'; if(s<3600)return Math.round(s/60)+' min';
  return Math.floor(s/3600)+' h '+Math.round((s%3600)/60)+' min'}
const fmt=n=>n.toLocaleString('en-US');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ═══════════════════════════════════════════════════════════════════════════
// 1. the alphabet + translation table (MEMORY-DASHBOARD-DESIGN §4.2, §12)
// ═══════════════════════════════════════════════════════════════════════════
const FAM=[
  {key:'intent',      word:'goals',         color:'#ffd36b'},
  {key:'control',     word:'plans',         color:'#9a86ff'},
  {key:'problem',     word:'problems',      color:'#ff6a4a'},
  {key:'knowledge',   word:'knowledge',     color:'#00d4ff'},
  {key:'feedback',    word:'your feedback', color:'#f4fbff'},
  {key:'delivery',    word:'deliveries',    color:'#5dffb0'},
  {key:'memory',      word:'remembering',   color:'#d36bff'},
  {key:'safety',      word:'safety',        color:'#ff9b3d'},
  {key:'environment', word:'the world',     color:'#6b9bff'},
];
const FAMI=Object.fromEntries(FAM.map((f,i)=>[f.key,i]));
const LABELS={
  intent:['GOAL_SET','GOAL_REFINED','CLARIFY_ASKED','CLARIFY_ANSWERED','PREFERENCE_STATED','GOAL_ABANDONED'],
  control:['PLAN_MADE','REPLAN','PIVOT','SPLIT','DELEGATED','ESCALATED','HALTED','BUDGET_HIT'],
  problem:['OBSTACLE','BUG','ATTEMPT','DEAD_END','RESOLUTION','FIX','VERIFIED_RESOLUTION','VERIFIED_FIX'],
  knowledge:['OBSERVED','CLAIM_CORROBORATED','CLAIM_UPDATED','CLAIM_CONTRADICTED','SOURCE_UNRELIABLE','BELIEF_STALE'],
  feedback:['CONFIRMATION','CORRECTION','APPROVAL','DENIAL','NO_RESPONSE'],
  delivery:['ANSWER_GIVEN','ARTIFACT_PRODUCED','NARRATED','CARD_SHOWN'],
  memory:['RECALL_DELIVERED','RECALL_USED','RECALL_HELPED','RECALL_MISLED','RECALL_MISSED','OFFLOADED','RESTRETCHED','LESSON','LANDMARK_PROMOTED','LANDMARK_STALE','CHAIN_CREATED','CHAIN_VARIANT'],
  safety:['UNSAFE_REFUSED','ESCALATED_UNSURE','INJECTION_SUSPECTED','PERMISSION_DENIED'],
  environment:['DEPENDENCY_CHANGED','RESOURCE_LIMIT','WORLD_CHANGED'],
};
// the topic-domain registry (the 12 values memory_chain.topic_domain carries); they are the
// TERRITORIES of the lattice; the event families are the activity inside them
const DOMAINS=['general','web','science','data','finance','ai','design','mobile','systems','devops','security','hardware'];
const DOM_WORD={general:'everyday',web:'the web',science:'science',data:'data',finance:'money',ai:'AI & models',design:'design',
  mobile:'mobile',systems:'systems & code',devops:'running things',security:'security',hardware:'hardware'};
const DOM_COL={general:'#9fb4c4',web:'#00d4ff',science:'#7fe8a8',data:'#ffd36b',finance:'#e8c25a',ai:'#d36bff',design:'#ff7fbf',
  mobile:'#7fa8ff',systems:'#5dffd0',devops:'#ff9b3d',security:'#ff6a4a',hardware:'#c8a87f'};
const READ={
  GOAL_SET:'you set a goal',GOAL_REFINED:'the goal got sharper',CLARIFY_ASKED:'IRIS asked what you meant',CLARIFY_ANSWERED:'you clarified',
  PREFERENCE_STATED:'you said what you prefer',GOAL_ABANDONED:'a goal was dropped',
  PLAN_MADE:'made a plan',REPLAN:'changed the plan',PIVOT:'changed direction',SPLIT:'split the work into parallel paths',
  DELEGATED:'handed work to a helper',ESCALATED:'asked for help',HALTED:'stopped on purpose',BUDGET_HIT:'ran out of budget',
  OBSTACLE:'hit an obstacle',BUG:'found a bug',ATTEMPT:'tried a fix',DEAD_END:'reached a dead end',RESOLUTION:'found a way through',
  FIX:'wrote a fix',VERIFIED_RESOLUTION:'the way through held',VERIFIED_FIX:'the fix passed its test',
  OBSERVED:'noticed something',CLAIM_CORROBORATED:'a second source agreed',CLAIM_UPDATED:'updated a belief',
  CLAIM_CONTRADICTED:'a belief was contradicted',SOURCE_UNRELIABLE:'a source proved unreliable',BELIEF_STALE:'a belief went stale',
  CONFIRMATION:'you confirmed',CORRECTION:'you corrected IRIS',APPROVAL:'you approved',DENIAL:'you said no',NO_RESPONSE:'no reply came',
  ANSWER_GIVEN:'answered you',ARTIFACT_PRODUCED:'made something',NARRATED:'spoke an update',CARD_SHOWN:'showed you a card',
  RECALL_DELIVERED:'remembered something',RECALL_USED:'used what it remembered',RECALL_HELPED:'remembering this helped',
  RECALL_MISLED:'remembering this misled',RECALL_MISSED:'forgot something it knew',APERTURE_DROPPED:'let a memory leave its mind',
  OFFLOADED:'set a thought aside',RESTRETCHED:'brought a thought back',PREMATURE_EVICTION:'let a thought go too early',
  LESSON:'learned a lesson',LANDMARK_PROMOTED:'IRIS is now sure about this',LANDMARK_STALE:'a certainty went stale',
  LANDMARK_DEMOTED:'a certainty was withdrawn',CHAIN_CREATED:'learned a way of working',CHAIN_VARIANT:'found a variation that works',
  UNSAFE_REFUSED:'refused something unsafe',ESCALATED_UNSURE:'checked with you when unsure',INJECTION_SUSPECTED:'spotted a manipulation attempt',
  PERMISSION_DENIED:'was not allowed',DEPENDENCY_CHANGED:'a dependency changed',RESOURCE_LIMIT:'hit a limit of this machine',WORLD_CHANGED:'the world changed',
};
const readEvent=e=>READ[e.label]||((FAM[FAMI[e.family]]||{word:'other'}).word+' · '+String(e.label||'').toLowerCase().replace(/_/g,' '));
// the store keeps raw prompts, thread ids and node labels; the face says what the thing is (UX-PLAN §1, §6.4)
// a task-path claim is stored as its task prompt: "The project is in <folder>. <the task>" -> the task, and the folder's name
const claimParts=c=>{const t=String(c||''),m=t.match(/^The project is in (.+?)\.\s+([\s\S]+)$/);
  return m?{text:m[2],where:m[1].split(/[\\/]/).pop()}:{text:t,where:null}};
// ids of the chat's own connection: memory written under them did not record its conversation ("session" is retired)
const THREAD_WORD={voice_headless:'spoken to IRIS, no chat open',session_iris_integration:'IRIS chat, no strand chosen',
  session_iris:'IRIS chat, strand not recorded'};
const threadTitle=t=>{t=String(t||'');if(THREAD_WORD[t])return THREAD_WORD[t];
  if(t.startsWith('[eval] '))return 'test run · '+t.slice(7).replace(/_/g,' ');
  // a thread named by its creation time in ms ("1792864722790-1"): say when, not the number
  if(/^\d{13}(-\d+)?$/.test(t))return 'a conversation from '+new Date(+t.slice(0,13)).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  return /^[\w-]+$/.test(t)&&/[_-]/.test(t)?t.replace(/[_-]+/g,' ').replace(/\bsession\b/g,'chat'):t};   // an id, not a title: at least make it words
const NODE_WORD={tool_none:'a step that used no tool',session_pattern:'a habit of how you work',stated_style:'a style you asked for',
  stated_conduct:'a way of working you asked for',hardware:'this machine'};
const nodeWord=lb=>{lb=String(lb||'');return NODE_WORD[lb]||(/^domain_/.test(lb)?'work about '+lb.slice(7).replace(/_/g,' ')
  :/^tool_/.test(lb)?'the '+lb.slice(5).replace(/_/g,' ')+' tool':lb.replace(/_/g,' '))};
// the tools of a task-path claim, in order, repeats folded ("read file ×3"); tool_none is a step with no tool
const claimHow=l=>{const st=(l.steps||[]).filter(s=>s.space==='toolpath');if(!st.length)return '';
  const tools=st.map(s=>String(s.label||'').replace(/^tool_/,'')).filter(t=>t&&t!=='none').map(t=>t.replace(/_/g,' '));
  if(!tools.length)return `${st.length} step${st.length===1?'':'s'} · which tools they used was not recorded`;
  const run=[];for(const t of tools){const r=run[run.length-1];if(r&&r.t===t)r.n++;else run.push({t,n:1})}
  return 'how: '+run.map(r=>r.n>1?`${r.t} ×${r.n}`:r.t).join(' → ')};
// evidence ladder = the visual hierarchy (§4.2, §11). user > recurrence/corroboration > test/completion > verifier > claim > none
const EVID={user:1,recurrence:.86,corroboration:.86,test:.72,completion:.72,verifier:.45,claim:.28,none:.12};
const EVID_WORD={user:'you confirmed this',test:'a test passed',completion:'the task finished',recurrence:'it held up again',
  corroboration:'an independent source agreed',verifier:'the reviewer checked it',claim:'IRIS reported this',none:'unconfirmed'};
const EVID_COL={user:'#f4fbff',recurrence:'#7fe8ff',corroboration:'#7fe8ff',test:'#5dffb0',completion:'#5dffb0',verifier:'#4f8fb0',claim:'#56707e',none:'#2c3a42'};
const OUTSIDE=new Set(['user','recurrence','corroboration','test','completion']);
const CLUSTER_WORD={preference:'your preferences',implement:'building',research:'research',debug:'fixing things',
  voice:'voice',environment:'this machine',workflow:'ways of working'};
const KIND_WORD={screen:'screenshots',web:'web captures',code:'code',doc:'documents',chart:'charts',audio:'audio',image:'images',terminal:'test runs',video:'videos'};
const ORACLE_PLAIN={tool_choice:'picking the next tool',escalate_incomplete:'knowing a result is incomplete',needs_action:'knowing when a step needs a tool',
  review_verdict:'judging its own steps',user_feedback:'reading what you meant',narration:'deciding what to say aloud',browser_next:'choosing where to click next',
  tool_approval:'predicting if a tool call will work',depth_met:'knowing when research is deep enough',web_intent:'knowing when to search the web',
  click_safety:'knowing if a click is safe',call_closing:'knowing a call was the last one',recovery_strategy:'choosing how to recover',
  sufficient:'knowing an answer is enough',event_family:'sorting what happened',event_type:'naming what happened',
  depth_route:'choosing whether to dig deeper',done:'knowing a goal is done',presentation:'choosing how to show the answer',
  mode:'choosing how to work on a step (retired)'};
// event_type:<family> is one consumer per family: name the family
const oracleWord=c=>{const [b,f]=String(c).split(':');return (ORACLE_PLAIN[b]||b.replace(/_/g,' '))+(f?' · '+((FAM[FAMI[f]]||{}).word||f):'')};

// ── Kyudo trust channel (nodes.source_channel): 4 system · 3 you · 2 verified · 1 outside · 0 untrusted;
// null = legacy internal. The membrane carries it as texture (porous + pale when weak), never as glare.
const CHAN_WORD={4:'set by the system',3:'came from you',2:'came from a verified source',1:'came from an outside source',0:'came from a source nobody vouches for'};
const chanWord=c=>c==null?'an older memory, from inside IRIS':CHAN_WORD[c]||'';
const LOCK_WORD={4:'only the system writes here',3:'only you and the system write here',2:'verified sources and above write here',
  1:'outside sources may write here',0:'any source may write here'};
const SPACE_WORD={conduct:'how you like to work',domain:'what you work on',style:'how you like to be spoken to',chrono:'when you work',
  context:'what goes on around the work',capability:'what IRIS can do',toolpath:'which tools worked'};
// membrane tint per channel: cool and grey when weak, warm when strong (dim on purpose)
const CHAN_TINT=['#7d7a8c','#8793ad','#9fb8c8','#cdd6d2','#dcd2b4'];
const chanTint=c=>CHAN_TINT[c==null?3:clamp(Math.round(c),0,4)];
// pins (MEMORY-FOUNDATION-ANALYSIS 13.3): explicit memory, held not earned
const PIN_TYPES={note:{col:'#e6d79c',word:'a note'},file:{col:'#8fb8ff',word:'a file'},folder:{col:'#7fa0d8',word:'a folder'},
  image:{col:'#ff9ec4',word:'an image'},doc:{col:'#d3dbe2',word:'a document'},url:{col:'#6fe3d2',word:'a web page'},
  decision:{col:'#ffb066',word:'a decision'},fragment:{col:'#b9a0ff',word:'a fragment'},checkpoint:{col:'#f3ead0',word:'a checkpoint'}};
const pinType=t=>PIN_TYPES[t]||PIN_TYPES.note;
// the immune response, in plain words
const QUORUM_WORD={update_velocity_anomaly:'something was written unusually fast',topological_violation:'the work drifted off its path',
  channel_trust_violation:'an untrusted source touched trusted ground',landmark_activation_anomaly:'a certainty fired unusually often',
  quorum_reorganization_reset:'the guard relaxed the territory'};
// territories whose key the registry does not know get a stable hue from the key
const hueCol=k=>{let h=0;for(const c of String(k))h=(h*31+c.charCodeAt(0))%360;return `hsl(${h},50%,64%)`};
const domCol=k=>DOM_COL[k]||hueCol(k);
const domWord=k=>DOM_WORD[k]||String(k).replace(/[_\/-]+/g,' ');

// ═══════════════════════════════════════════════════════════════════════════
// 2. memory — real snapshot when present, otherwise a schema-faithful generator
// ═══════════════════════════════════════════════════════════════════════════
function synthMemory(){
  rng=mulberry32(1014);
  const T=nowS(), DAY=86400;
  const OBJ=['research local GGUF quantization','fix the TTS warm-up hang','make the orb readable on pale wallpapers','speed up the cold start',
   'summarize this week\'s emails','add strand cascade delete','find why the in-app browser stalls','plan a long weekend in Lisbon',
   'compare three note-taking apps','write tests for the turn store','debug the wake word on a noisy mic','draft a reply to the landlord',
   'index the memory events table','explain the Caducean phase model','design the per-project port registry','clean up the downloads folder',
   'research robot vacuum reviews','find a recipe with what is in the fridge','split the agent kernel file','find why replies took 3 minutes',
   'learn my calendar habits','convert the report to PDF','scan the changelog for breaking changes','tune the narration timing',
   'chart my sleep data','start the dev server for the side project','research the Nostr protocol','fix the flaky ledger test',
   'review the oracle bar report','write the weekly status note','find the cause of the 6 GB memory file','order the reading list by topic',
   'measure the research eval','outline the hive network idea','repair tool-call arguments','learn my preferred voice speed',
   'compare two laptops for local models','build the memory dashboard mockup'];
  const sessions=OBJ.map((o,i)=>{const live=i===OBJ.length-1;
    const started=live?T-1500:T-(OBJ.length-1-i)*DAY*1.55-rand(0,DAY*.6);
    const dur=live?0:rand(500,3.2*3600);
    return {id:'sess_'+i,objective:o,started,ended:live?null:started+dur,exit:live?'live':(rng()<.82?'natural':'drift'),traj:[],events:[],episodes:[]}});
  const DKW={web:/research|capture|review|changelog|nostr|search/,ai:/model|gguf|oracle|quantiz|narration|voice/,data:/chart|sleep|index|memory|reading list/,
    design:/orb|dashboard|wallpaper|mockup|hive/,systems:/kernel|ledger|store|test|cold start|browser|tts|wake word|arguments|turn|strand/,
    devops:/dev server|eval|downloads|port|pdf/,hardware:/laptop|mic|vacuum/,science:/caducean|phase|recipe/,finance:/landlord|rent|budget/};
  for(const s of sessions)s.domain=Object.keys(DKW).find(k=>DKW[k].test(s.objective))||'general';
  for(const s of sessions){let ph=rand(0,6);const n=randi(26,64);for(let k=0;k<n;k++){ph+=rand(.12,.5);
    s.traj.push({x:Math.sin(ph)*.85+gauss()*.08,y:Math.cos(ph*.7),xi:rand(),u:.5+.5*Math.sin(ph*1.3)})}}

  const PREF=['You prefer short spoken replies with the details on screen.','You like a voice slightly faster than the default.',
   'You prefer metric units.','You want IRIS to ask before it edits its own code.','You read the news in the evening, not the morning.',
   'You call the side panel "the wing".','You keep your reading list ordered by topic, not by date.','Recipes for you should leave out nuts.',
   'In Lisbon you prefer walkable neighbourhoods to airport hotels.','Your landlord answers email faster than phone calls.',
   'Your calendar is busiest on Tuesday mornings.','You like dark themes with one bright accent.','Downloads older than 90 days are safe to archive, you said.',
   'You correct spelled-out numbers to digits.','The weekly status note goes out on Fridays.'];
  const ENV=['The C: drive is a slow hard disk, so cold reads take ten times longer.','Local models live on the fast D: drive.',
   'The browser stalls when the disk pages the model back in.','The wake word fails when the fan noise is high.',
   'Shell paths with spaces need quotes on this machine.','This machine has 32 GB of memory, so one large local model fits at a time.',
   'The text-to-speech worker must be warm before IRIS reports ready.'];
  const DEBUG=['A fix is only a fix when its test passes.','Two writers on one database connection cause flaky failures.',
   'Unindexed scans on large tables stall replies.','Tests that time out usually wait on a background thread.',
   'The memory file grew from re-nested copies, not from real data.','Tool calls fail most often on wrong argument names.',
   'A swallowed error on a path that should never fail is an alarm.','Editing files in place keeps em dashes intact; rewriting them garbles them.'];
  const IMPL=['A coding step works when it sees your exact words.','Running one test file is faster than running the whole suite here.',
   'Large files are best read in parts.','A dev server needs a port no other thread uses.','A reply that names a file should open it on the side.'];
  const RES=['Splitting research into parallel paths finds sources faster.','Gadget reviews older than two years are less useful.',
   'Breaking changes hide under "Migration" headings in changelogs.','Pages that refuse robots are skipped, not retried.',
   'A source that contradicted itself twice is unreliable.','Laptops for local models need at least 32 GB of memory.'];
  const VOICE=['Replies under 20 seconds keep a conversation flowing.','Narration should not repeat what is on screen.',
   'The orb must stay visible while you speak.','Summaries land better with three points than with ten.'];
  const WF=['Asking one clarifying question beats guessing on a vague task.','Charts read better with direct labels than with a legend.',
   'A plan with one clear goal per step fails less.','Measure first, then fix the cause, then guard it.'];
  const TOOLS=['The web search','The file reader','The test runner','The browser','The shell','The editor','The vision model','The calendar tool'];
  const CONDS=['when the request is quoted exactly','when it runs in the project folder','after the page has finished loading','when paths are absolute',
   'when the query names a site','on files under 1 MB','when it runs after the plan','when the step has one clear goal'];
  const DOMS=['Cooking','Gadget','Travel','Coding','Fitness','Home repair'];
  const SRCS=['official documentation','recent reviews','two independent sources','your own notes','the project\'s tests','forum answers marked as accepted'];
  const claims=[];
  const add=(arr,c)=>arr.forEach(x=>claims.push([x,c]));
  add(PREF,'preference');add(ENV,'environment');add(DEBUG,'debug');add(IMPL,'implement');add(RES,'research');add(VOICE,'voice');add(WF,'workflow');
  for(const t of TOOLS)for(const c of CONDS)if(rng()<.55)claims.push([`${t} succeeds more often ${c}.`,pick(['implement','workflow','research','debug'])]);
  for(const d of DOMS)for(const s of SRCS)if(rng()<.5)claims.push([`${d} questions are answered best from ${s}.`,'research']);

  const landmarks=claims.map(([claim,cls],i)=>{
    const cand=rng()<.3;
    const kinds=cand?['verifier','claim','none']:['user','recurrence','corroboration','test','completion'];
    const ev=[];const n=cand?randi(0,2):randi(1,6);
    for(let k=0;k<n;k++){const kind=cls==='preference'&&!cand&&k===0?'user':pick(kinds);ev.push({kind,at:T-rand(0,DAY*55),session:pick(sessions).id})}
    const born=T-rand(DAY*.5,DAY*58);
    return {id:'lm_'+i,claim,cls,tier:cand?'candidate':'landmark',permanent:!cand&&rng()<.6,evidence:ev,
      activations:cand?randi(0,4):Math.round(Math.pow(rng(),2)*120)+1,contradictions:rng()<.12?randi(1,3):0,
      last_activated:T-rand(60,DAY*20),last_verified:T-rand(DAY,DAY*40),born,session:pick(sessions).id,
      fams:[FAMI.knowledge,FAMI.memory,pick([0,1,2,4,5,7,8])],
      domain:rng()<.7?({preference:'general',implement:'systems',research:'web',debug:'systems',voice:'ai',environment:'hardware',workflow:'general'}[cls]||'general'):pick(DOMAINS),
      // Kyudo channel: what you confirmed came from you; learned certainties came through a verified path; a candidate may rest on weak sources
      channel:ev.some(e=>e.kind==='user')?3:(cand?pick([1,1,0,2,null]):pick([2,2,2,4,3]))};
  });
  const edges=[];
  for(let i=0;i<landmarks.length;i++){const k=randi(1,3);for(let j=0;j<k;j++){
    let b=rng()<.75?landmarks.findIndex((l,ix)=>ix>i&&l.cls===landmarks[i].cls&&rng()<.3):randi(0,landmarks.length-1);
    if(b<0||b===i)continue;const used=rng()<.55;edges.push({id:'le_'+edges.length,a:i,b,score:rand(.3,1),traversals:used?randi(1,60):0,hits:randi(0,30),misses:randi(0,6),grew:used&&rng()<.22})}}
  const merges=[];for(let i=0;i<34;i++)merges.push({survivor:randi(0,landmarks.length-1),absorbed_label:pick(claims)[0],overlap:rand(.7,.97)});

  const TOOLSEQ=['search','read_file','run_tests','edit_file','browser_open','browser_click','shell','vision','write_file','speak'];
  const events=[],episodes=[];let eid=0;
  for(const s of sessions){
    const end=s.ended||T;const nEp=randi(1,3);
    for(let e=0;e<nEp;e++){const out=weighted([['success',.62],['partial',.23],['failure',.15]]);
      const t0=lerp(s.started,end,e/nEp),t1=lerp(s.started,end,(e+1)/nEp);
      const ep={id:'ep_'+episodes.length,session:s.id,summary:e===0?s.objective:pick(['check the result','retry with a smaller step','write it up','verify the fix','read the source again']),
        outcome:s.exit==='live'&&e===nEp-1?'running':out,score:out==='success'?rand(.75,1):out==='partial'?rand(.4,.7):rand(.05,.35),
        corrected:rng()<.09,confirmed:rng()<.22,duration:t1-t0,tools:Array.from({length:randi(3,9)},()=>pick(TOOLSEQ)),ts:t1,
        failure_reason:out==='failure'?pick(['the page refused automated access','the test kept timing out','the plan missed a step','a dependency was missing']):null};
      episodes.push(ep);s.episodes.push(ep.id);
      const seq=[['intent','GOAL_SET','user','user','advances']];
      seq.push(['control','PLAN_MADE','agent','claim','advances']);
      const n=randi(10,34);
      for(let k=0;k<n;k++){const r=rng();
        if(r<.2)seq.push(['knowledge',pick(['OBSERVED','OBSERVED','CLAIM_CORROBORATED','CLAIM_UPDATED','CLAIM_CONTRADICTED']),'tool',pick(['claim','corroboration','claim']),'advances']);
        else if(r<.34)seq.push(['problem',pick(['OBSTACLE','BUG','DEAD_END']),pick(['tool','world']),'claim','sets_back']);
        else if(r<.46)seq.push(['problem',pick(['ATTEMPT','FIX','RESOLUTION']),'agent','claim','neutral']);
        else if(r<.52)seq.push(['problem','VERIFIED_FIX','tool','test','advances']);
        else if(r<.64){seq.push(['memory','RECALL_DELIVERED','agent','claim','neutral']);seq.push(['memory','RECALL_USED','agent','claim','advances']);
          seq.push(['memory',rng()<.8?'RECALL_HELPED':'RECALL_MISLED','agent',rng()<.5?'completion':'verifier',rng()<.8?'advances':'sets_back'])}
        else if(r<.70)seq.push(['control',pick(['SPLIT','REPLAN','PIVOT','DELEGATED']),'agent','claim',pick(['neutral','sets_back','advances'])]);
        else if(r<.80)seq.push(['delivery',pick(['NARRATED','CARD_SHOWN']),'agent','claim','neutral']);
        else if(r<.83)seq.push(['safety',pick(LABELS.safety),'agent','verifier','neutral']);
        else if(r<.86)seq.push(['environment',pick(LABELS.environment),'world','claim','sets_back']);
        else if(r<.92)seq.push(['memory',pick(['LESSON','OFFLOADED','RESTRETCHED','LANDMARK_PROMOTED','CHAIN_CREATED']),'agent',pick(['recurrence','claim','completion']),'advances']);
        else seq.push(['intent',pick(['GOAL_REFINED','CLARIFY_ASKED','CLARIFY_ANSWERED']),pick(['user','agent']),pick(['user','claim']),'advances']);
      }
      seq.push(['delivery',pick(['ANSWER_GIVEN','ARTIFACT_PRODUCED']),'agent','completion','advances']);
      if(rng()<.5)seq.push(['feedback',ep.corrected?'CORRECTION':pick(['CONFIRMATION','APPROVAL','NO_RESPONSE']),'user','user',ep.corrected?'sets_back':'advances']);
      seq.forEach((q,k)=>{const lm=q[0]==='memory'&&rng()<.85?randi(0,landmarks.length-1):null;
        events.push({id:'ev_'+(eid++),ts:lerp(t0,t1,(k+rand(0,.8))/seq.length),family:q[0],label:q[1],actor:q[2],evidence:q[3],valence:q[4],
          episode:ep.id,session:s.id,landmark:lm,domain:rng()<.85?s.domain:pick(DOMAINS)})});
    }
  }
  events.sort((a,b)=>a.ts-b.ts);
  for(const e of events){const s=sessions.find(x=>x.id===e.session);s.events.push(e)}
  const AK=[['screen',8],['web',7],['code',9],['doc',7],['chart',5],['audio',4],['image',4],['terminal',5],['video',4]];
  const FOLDERS={screen:['screenshots','browser captures'],web:['nostr','reviews','model docs'],code:['IRISVOICE','side-project'],doc:['notes','reports','letters'],
    chart:['health','evals'],audio:['voice notes','narration'],image:['generated','photos'],terminal:['test runs','eval runs'],video:['screen recordings','clips']};
  const ANAMES={screen:['orb-on-pale-wallpaper.png','chat-wing-dark.png','browser-stall.png','tier-card.png','strand-list.png','settings-voice.png','matrix-rows.png','oracle-panel.png','dev-server.png'],
    web:['capture · nostr protocol spec','capture · vacuum review roundup','capture · gguf quant table','capture · lisbon tram map','capture · changelog 4.2','capture · sleep science article','capture · laptop benchmarks'],
    code:['turn_store_test.py','port_registry.ts','tts_warmup.py','memory_events_index.sql','strand_delete.py','kernel_split_plan.py','arg_repair.py','orb_halo.tsx','ledger_lane.py'],
    doc:['lisbon-weekend.md','weekly-status-10-10.md','reply-to-landlord.md','hive-network-outline.md','report.pdf','reading-list.md','kernel-split-notes.md'],
    chart:['sleep-last-30-days.png','reply-times-eval.svg','store-size-growth.svg','oracle-bar-progress.svg','quant-quality-vs-size.svg'],
    audio:['voice-note · landlord.wav','voice-note · grocery list.wav','narration-sample.wav','voice-speed-test.wav'],
    image:['generated · orb concept.png','fridge-photo.jpg','lisbon-sunset.jpg','whiteboard.jpg'],
    terminal:['pytest · turn store','pytest · ledger lane','eval run · coding 15/15','eval run · research','cargo test · tauri'],
    video:['orb-swallow-demo.mp4','voice-turn-recording.mp4','browser-stall-repro.webm','tunnel-flythrough.mp4']};
  const artifacts=[];
  for(const [k,n] of AK)for(let i=0;i<n;i++){const s=pick(sessions);artifacts.push({id:'art_'+artifacts.length,kind:k,name:ANAMES[k][i%ANAMES[k].length],folder:pick(FOLDERS[k]),
    session:s.id,ts:s.started+rand(60,3600),weight:rand(.6,1.6)*(rng()<.15?2:1),seed:randi(1,1e6)})}
  const oracle=[
    ['tool_choice','enforced',688,.76,.019,.91],['escalate_incomplete','enforced',513,.84,.03,.9],['needs_action','enforced',216,.80,.04,.92],
    ['review_verdict','sampled',1381,.63,.04,.86],['user_feedback','shadow',165,.91,.054,.88],['narration','shadow',332,.7,.054,.84],
    ['browser_next','shadow',126,.66,.08,.7],['tool_approval','shadow',1880,.56,.07,.75],['depth_met','shadow',401,.40,.12,.5],
    ['web_intent','shadow',199,.49,.11,.55],['click_safety','shadow',92,.6,.09,.7],['call_closing','shadow',657,.6,.06,.8],
    ['recovery_strategy','shadow',40,.55,.1,.6],['sufficient','shadow',35,.55,.1,.6],['event_family','shadow',24,.6,.1,.6],['event_type','shadow',18,.6,.1,.6],
  ].map(([c,state,rows,auroc,ece,precision])=>({consumer:c,state,rows,auroc,ece,precision}));
  const famCounts={intent:1450,control:3920,problem:2610,knowledge:4380,feedback:610,delivery:2950,memory:2260,safety:140,environment:481};
  const mind=['your exact request','plan · step 3 of 5','turn_store.py · lines 40–120','the failing test output','what "the wing" means to you',
    'run one test file, not the suite','last week\'s similar fix','the project folder layout','your voice speed preference','an open question for you',
    'the search results from step 2','the error from the shell'];
  // ── sectors: roots are the topic-domain territories, children nest inside them (MEMORY-FOUNDATION-ANALYSIS 5.1)
  const KIDS={systems:['memory','tests','lanes'],web:['research','browsing'],ai:['voice','oracle'],devops:['ports'],data:['store'],design:['orb']};
  const sectors=DOMAINS.map(d=>({key:d,parent:null,label:DOM_WORD[d],status:'proven',members:0}));
  for(const [d,ks] of Object.entries(KIDS))ks.forEach((k,j)=>sectors.push({key:d+'/'+k,parent:d,label:k,status:(d+k).length%3===0?'candidate':'proven',members:0}));
  landmarks.forEach(l=>{const ks=KIDS[l.domain];if(ks&&rng()<.55){l.sector=l.domain+'/'+pick(ks)}});
  sectors.forEach(s=>{s.members=landmarks.filter(l=>s.parent?l.sector===s.key:l.domain===s.key).length});
  // ── coordinate spaces (the registry) and the nodes in them; a node's channel is never below its space's write lock
  const spaces=[['conduct',3,0],['domain',1,1],['style',3,2],['chrono',3,3],['context',2,4],['capability',4,5],['toolpath',4,null]]
    .map(([id,lock,ro])=>({id,description:SPACE_WORD[id],active:true,write_lock:lock,render_order:ro}));
  const NPER={conduct:6,domain:18,style:8,chrono:6,context:20,capability:12,toolpath:64};
  const nodes=[];
  for(const sp of spaces)for(let k=0;k<NPER[sp.id];k++){
    const floor=rng()<.28;  // a quarter sit on the stated floor: stated, never re-earned
    nodes.push({id:'nd_'+nodes.length,space:sp.id,label:sp.id==='toolpath'?pick(['write_file','read_file','run_tests','tool_none','search']):sp.id+' '+(k+1),
      conf:floor?.4:clamp(.4+Math.pow(rng(),.8)*.55,.4,.95),chan:rng()<.1?null:clamp(sp.write_lock+(rng()<.45?0:randi(0,4-sp.write_lock)),0,4),
      born:T-rand(DAY*.5,DAY*55),used:Math.round(Math.pow(rng(),2.4)*40)})}
  const nodeEdges=[];
  for(let i=0;i<46;i++){const a=randi(0,nodes.length-1),b=randi(0,nodes.length-1);if(a===b)continue;
    nodeEdges.push({a,b,score:rand(.3,.95),traversals:randi(0,16),observations:randi(0,18),last:T-rand(0,DAY*30)})}
  // ── pins: explicit memory (note/file/folder/image/doc/url/decision/fragment/checkpoint)
  const PT=[['folder','IRISVOICE repo root','systems'],['file','memory.db schema','systems'],['decision','Every store write goes through a lane','systems'],
    ['doc','Oracle bar report','ai'],['url','Nostr protocol spec','web'],['image','Strand cascade sketch','design'],['note','You prefer short spoken replies','general'],
    ['fragment','Argument-repair snippet','systems'],['decision','Keep the orb readable on pale wallpapers','design'],['url','GGUF quantization table','ai'],
    ['file','port_registry.ts','devops'],['note','Landlord answers email faster than calls','finance'],['doc','Weekly status note','general'],
    ['checkpoint','Paused: turn store tests','systems'],['checkpoint','Paused: strand cascade delete','design'],['image','Lisbon tram map','general'],['decision','Measure first, then fix, then guard','systems']];
  const pins=PT.map(([type,title,domain],i)=>{const near=landmarks.map((l,k)=>[l,k]).filter(([l])=>l.domain===domain);
    const nl=type==='checkpoint'?0:randi(1,4),refs=[];for(let j=0;j<nl&&near.length;j++)refs.push({t:'landmark',id:pick(near)[0].id});
    if(rng()<.5&&artifacts.length)refs.push({t:'artifact',id:pick(artifacts).id});if(rng()<.35)refs.push({t:'node',id:pick(nodes).id});
    const sess=pick(sessions);if(type==='checkpoint'){refs.push({t:'thread',id:sess.id})}else if(rng()<.5)refs.push({t:'thread',id:pick(sessions).id});
    const kids=KIDS[domain];
    return {id:'pin_'+i,title,type,created:type==='checkpoint'?(sess.ended||sess.started+600)-30:sess.started+rand(60,900),permanent:rng()<.3,held:i%4===1||type==='checkpoint'&&i%2===1,
      links:refs.length+randi(0,3),refs,domain,sector:kids&&rng()<.5?domain+'/'+pick(kids):null,session:sess.id}});
  // ── immune response: the quorum log. Live rows count toward the threat; shadow rows are only measured; the reset is the region relaxing
  const live=landmarks.length-1;
  const quorum=[['topological_violation',.20,.20,0],['channel_trust_violation',.25,.45,0],['landmark_activation_anomaly',0,.45,1],['topological_violation',.20,.65,0],
    ['quorum_reorganization_reset',0,0,0],['update_velocity_anomaly',.15,0,1],['topological_violation',.20,.20,0],['landmark_activation_anomaly',0,.20,1],
    ['update_velocity_anomaly',.15,.20,1],['channel_trust_violation',.25,.45,0],['topological_violation',.20,.65,0],['quorum_reorganization_reset',0,0,0]]
    .map(([signal,weight,threat,shadow],i)=>({ts:T-(12-i)*DAY*.18,session:pick(sessions).id,signal,weight,threat,shadow:!!shadow,landmark:signal==='landmark_activation_anomaly'?landmarks[randi(0,live)].id:null}));
  // recalls: on recent turns the memory hands earlier steps (DER chain rows) to the agent's steps
  const DID=['Read the failing test to see what it expects','List the project directory to understand the structure','Run the test suite after the edit',
    'Search the web for the release notes','Open the config file and check the port','Edit the parser to accept the new field','Grep for the old function name'];
  const RTOOL=['read_file','list_directory','run_command','search','read_file','edit_file','grep_files'];
  const recalls=[];sessions.slice().sort((a,b)=>b.started-a.started).slice(0,30).forEach(s=>{const older=sessions.filter(o=>o.started<s.started);if(!older.length)return;
    for(let t=0,nt=randi(1,2);t<nt;t++){const ts0=lerp(s.started,s.ended||T,rand(.1,.8)),n=randi(2,6),steps=[];
      for(let k=0;k<n;k++){if(rng()<.3)continue;const src=weighted([['neighbors',.7],['prior_research',.15],['chain_timeline',.1],['known_case',.05]]);
        const refs=Array.from({length:randi(1,3)},()=>{const o=pick(older),d=randi(0,DID.length-1);
          return {session:o.id,did:DID[d],result:rng()<.85?'success':'failure',tool:RTOOL[d],ts:lerp(o.started,o.ended||T,rng()),kind:'step'}});
        const oc=weighted([['helped',.72],['misled',.1],['none',.18]]);steps.push({step:'s'+(k+1),ts:ts0+k*20,source:src,outcome:oc==='none'?null:oc,refs})}
      if(steps.length)recalls.push({turn:s.id+':t'+t,session:s.id,ts:ts0,steps})}});
  recalls.sort((a,b)=>b.ts-a.ts);
  return {meta:{source:'synthetic — follows the data/memory.db schema',generated:T,counts:{events:18801,chain:20743,landmarks:2027,edges:6628,merges:1806,
    episodes:407,sessions:108,fragments:84712,artifacts:artifacts.length,pins:pins.length,nodes:nodes.length,spaces:spaces.length,quorum:quorum.length}},
    famCounts,sessions,events,landmarks,edges,merges,episodes,artifacts,oracle,mind,sectors,spaces,nodes,nodeEdges,pins,quorum,recalls};
}
function normalizeMemory(M){
  M.sessions=M.sessions||[];M.events=M.events||[];M.landmarks=M.landmarks||[];M.edges=M.edges||[];M.merges=M.merges||[];
  M.episodes=M.episodes||[];M.artifacts=M.artifacts||[];M.oracle=M.oracle||[];M.mind=M.mind||[];
  M.famCounts=M.famCounts||{};
  for(const f of FAM)if(M.famCounts[f.key]==null)M.famCounts[f.key]=M.events.filter(e=>e.family===f.key).length;
  // the newer concepts: a snapshot or a store that predates one simply has none of it
  M.sectors=(M.sectors||[]).filter(s=>s&&s.key&&s.status!=='dissolved');M.pins=M.pins||[];M.spaces=M.spaces||[];
  M.nodes=M.nodes||[];M.nodeEdges=M.nodeEdges||[];M.quorum=M.quorum||[];M.meta=M.meta||{};M.recalls=M.recalls||[];
  // sectors: roots are the territories, children nest inside them; with no registry the topic domains stand in
  const secBy=new Map(M.sectors.map(s=>[s.key,s]));
  const par=k=>{const p=secBy.get(k)?.parent;return p&&secBy.has(p)?p:null};
  const rootOf=k=>{let n=0;while(par(k)&&n++<6)k=par(k);return k};
  const childOf=k=>{let n=0;while(par(k)&&par(par(k))&&n++<6)k=par(k);return par(k)?k:null}; // the depth-1 ancestor
  M.sectorsOn=M.sectors.some(s=>!s.parent);
  const rootKeys=M.sectors.filter(s=>!s.parent).map(s=>s.key);
  const mapDom=d=>M.sectorsOn?(secBy.has(d)?rootOf(d):(secBy.has('general')?'general':rootKeys[0])):(DOMAINS.includes(d)?d:'general');
  for(const e of M.events){e.sector=M.sectorsOn&&secBy.has(e.domain)?childOf(e.domain):null;e.domain=mapDom(e.domain)}
  if(!M.domCounts){M.domCounts={};const k=(M.meta?.counts?.events||M.events.length)/Math.max(1,M.events.length);
    for(const e of M.events)M.domCounts[e.domain]=(M.domCounts[e.domain]||0)+k;for(const d in M.domCounts)M.domCounts[d]=Math.round(M.domCounts[d])}
  else if(M.sectorsOn){const dc={};for(const [k,n] of Object.entries(M.domCounts))dc[mapDom(k)]=(dc[mapDom(k)]||0)+n;M.domCounts=dc}
  if(M.sectorsOn)for(const s of M.sectors)if(!s.parent&&M.domCounts[s.key]==null)M.domCounts[s.key]=s.members||0;
  const sById=new Map(M.sessions.map(s=>[s.id,s]));
  for(const s of M.sessions){s.events=s.events||[];s.episodes=s.episodes||[];s.traj=s.traj||[];s.objective=threadTitle(s.objective||s.id)}
  if(M.sessions.every(s=>!s.events.length))for(const e of M.events){const s=sById.get(e.session);if(s)s.events.push(e)}
  for(const s of M.sessions)s.events.sort((a,b)=>a.ts-b.ts);
  M.sessions.sort((a,b)=>a.started-b.started);
  for(const l of M.landmarks){l.evidence=l.evidence||[];l.cls=l.cls||'workflow';l.fams=l.fams||[FAMI.knowledge,FAMI.memory];
    const cp=claimParts(l.claim);l.claim=cp.text;l.where=cp.where;
    l.sector=M.sectorsOn&&l.sector&&secBy.has(l.sector)?childOf(l.sector):null;
    l.domain=mapDom(l.domain);l.channel=l.channel==null?null:clamp(Math.round(l.channel),0,4);
    l.born=l.born||l.last_verified||l.last_activated||nowS()}
  M.sById=sById;M.epById=new Map(M.episodes.map(e=>[e.id,e]));
  M.lmIndex=new Map(M.landmarks.map((l,i)=>[l.id,i]));
  for(const e of M.events)if(typeof e.landmark==='string')e.landmark=M.lmIndex.has(e.landmark)?M.lmIndex.get(e.landmark):null;
  // a session's own territory: where most of its moments landed
  for(const s of M.sessions)if(!s.domain){const c={};for(const e of s.events)c[e.domain]=(c[e.domain]||0)+1;
    s.domain=Object.entries(c).sort((a,b)=>b[1]-a[1])[0]?.[0]||'general'}
  // nodes: confidence and channel come from the store; edges refer to nodes by index
  M.nIndex=new Map(M.nodes.map((n,i)=>[n.id,i]));
  for(const n of M.nodes){n.conf=clamp(n.conf??.5,0,1);n.chan=n.chan==null?null:clamp(Math.round(n.chan),0,4);n.born=n.born||nowS()-86400}
  M.nodeEdges=M.nodeEdges.filter(e=>e.a<M.nodes.length&&e.b<M.nodes.length);
  // pins: a territory (by domain, else the landmarks it ties to), the thread it belongs to, what it is tied to
  M.pins=M.pins.filter(p=>p&&p.id);
  for(const p of M.pins){p.refs=p.refs||[];p.type=PIN_TYPES[p.type]?p.type:'note';
    const lms=p.refs.filter(r=>r.t==='landmark'&&M.lmIndex.has(r.id)).map(r=>M.lmIndex.get(r.id));
    if(!p.domain&&lms.length){const c={};lms.forEach(k=>c[M.landmarks[k].domain]=(c[M.landmarks[k].domain]||0)+1);p.domain=Object.entries(c).sort((a,b)=>b[1]-a[1])[0][0]}
    p.sector=M.sectorsOn&&p.sector&&secBy.has(p.sector)?childOf(p.sector):null;p.domain=mapDom(p.domain||'general');
    p.links=Math.max(p.links||0,p.refs.length);
    if(!p.session||!sById.has(p.session)){const tr=p.refs.find(r=>(r.t==='thread'||r.t==='session')&&sById.has(r.id));
      p.session=tr?tr.id:(M.sessions.find(s=>s.started<=p.created&&p.created<=(s.ended||nowS()))?.id||null)}}
  // the immune log, oldest first
  M.quorum=M.quorum.filter(q=>q&&q.signal).sort((a,b)=>a.ts-b.ts);
  return M;
}
// index.html?real shows the exported snapshot of this machine's memory; the default is the
// schema-faithful demo, so the page always opens with the full experience.
const USE_REAL=!!opts.data;
const M=normalizeMemory(USE_REAL?opts.data:synthMemory());
// the Oracle view's richer record (GET /api/memory/oracle: job, the bar as a ladder, history, calibration curve)
if(Array.isArray(opts.oracle)){const by=new Map(opts.oracle.map(o=>[o.consumer,o]));for(const o of M.oracle){const r=by.get(o.consumer);if(r)Object.assign(o,r)}}
rng=mulberry32(77);
const T0=Math.min(...M.landmarks.map(l=>l.born),...M.sessions.map(s=>s.started),nowS()-86400);
const bestEvidence=l=>{let b='none',bv=0;for(const e of l.evidence){const v=EVID[e.kind]||0;if(v>bv){bv=v;b=e.kind}}return b};
// SYNC (design §18): one 0..1 value for how well a piece of memory holds together, read from outside evidence only.
//  claim     = its strongest outside evidence, held back while it is still a candidate, pulled down by contradictions
//  session   = how its tasks ended (success 1, partial .5, failure 0; a correction by you counts .7), blended with the
//              evidence strength of its moments; a session that drifted off loses a little
//  territory = the share of its claims that are proven (regSync, smoothed)
const syncClaim=l=>clamp((EVID[bestEvidence(l)]||0)*(l.tier==='candidate'?.6:1)*(1-.2*Math.min(3,l.contradictions||0))+(l.permanent?.05:0),0,1);
const syncSession=s=>{const eps=s.episodes.map(id=>M.epById.get(id)).filter(e=>e&&e.outcome!=='running');
  const ev=s.events.length?s.events.reduce((a,e)=>a+(EVID[e.evidence]??.2),0)/s.events.length:.3;
  const ep=eps.length?eps.reduce((a,e)=>a+(e.corrected?.7:e.outcome==='success'?1:e.outcome==='partial'?.5:0),0)/eps.length:null;
  return clamp((ep==null?ev:.65*ep+.35*ev)*(s.exit==='drift'?.85:1),0,1)};
// DESYNC is not low sync: missing evidence is "not proven yet", a failure or a setback is the memory not holding together
const desyncSession=s=>{const eps=s.episodes.map(id=>M.epById.get(id)).filter(e=>e&&e.outcome!=='running');
  const f=eps.length?eps.filter(e=>e.outcome==='failure').length/eps.length:0,b=s.events.length?s.events.filter(e=>e.valence==='sets_back').length/s.events.length:0;
  return clamp(f+b*2,0,1)};
const syncHTML=v=>{const p=Math.round(v*100),c=v>=.75?'#bfe9f6':v>=.5?'#d8cf9a':'#ff8a6a';
  return `<span class="syncr" style="color:${c}">sync <span class="sync"><i style="width:${p}%"></i></span>${p}%</span>`};
// territories: the domains that hold anything, largest first (max 12 = the shader's region slots)
const REG=Object.entries(M.domCounts).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]).slice(0,12).map(([d])=>d);
if(!REG.length)REG.push('general');
const REGI=Object.fromEntries(REG.map((d,i)=>[d,i]));
const regOf=d=>REGI[d]??REGI.general??0;
M.landmarks.forEach(l=>{l.dom=regOf(l.domain)});
// nested sub-territories: the children of the sector registry that sit under a drawn territory (depth 1; at most 12)
const SUB=(M.sectorsOn?M.sectors.filter(s=>s.parent&&REGI[s.parent]!=null):[]).sort((a,b)=>(b.members||0)-(a.members||0)).slice(0,12)
  .map(s=>({key:s.key,label:s.label||domWord(String(s.key).split('/').pop()),status:s.status||'proven',members:s.members||0,ri:REGI[s.parent]}));
const SUBI=Object.fromEntries(SUB.map((s,i)=>[s.key,i]));
M.landmarks.forEach(l=>{l.sub=l.sector&&SUBI[l.sector]!=null?SUBI[l.sector]:-1});
// landmark tracts grow only when their traversal count did: real = the count rose since this browser last saw the store
if(USE_REAL){let seen={};try{seen=JSON.parse(localStorage.getItem('iris.memory.edgeSeen')||'{}')}catch(e){}
  for(const e of M.edges){const k=e.id||('e'+e.a+'-'+e.b),prev=seen[k];e.grew=prev!=null&&(e.traversals||0)>prev;seen[k]=e.traversals||0}
  try{localStorage.setItem('iris.memory.edgeSeen',JSON.stringify(seen))}catch(e){}}
// what happens inside each territory: its three busiest kinds of event, in plain words; nested sectors follow
const domTop=REG.map((d,ri)=>{const c={};for(const e of M.events)if(e.domain===d)c[e.family]=(c[e.family]||0)+1;
  return [...Object.entries(c).sort((a,b)=>b[1]-a[1]).slice(0,3).map(([f,n])=>`${FAM[FAMI[f]]?.word||f} ${n}`),
    ...SUB.filter(s=>s.ri===ri).slice(0,3).map(s=>`↳ ${s.label}${s.status==='candidate'?' (still forming)':''} ${s.members}`)]});
const famTop={};
for(const f of FAM){const c={};for(const e of M.events)if(e.family===f.key)c[e.label]=(c[e.label]||0)+1;
  famTop[f.key]=Object.entries(c).sort((a,b)=>b[1]-a[1]).slice(0,3).map(([l])=>READ[l]||l.toLowerCase())}

// ═══════════════════════════════════════════════════════════════════════════
// 3. renderer, bloom, camera
// ═══════════════════════════════════════════════════════════════════════════
const canvas=document.getElementById('gl');
let renderer;
try{renderer=new THREE.WebGLRenderer({canvas,antialias:false,powerPreference:'high-performance'})}
catch(e){document.getElementById('err').style.display='flex';opts.onError?.(e);throw e}
// GPU is shared with local models: cap the pixel ratio and let quality fall back on slow frames.
let DPR=Math.min(devicePixelRatio||1,1.6);
renderer.setPixelRatio(DPR);renderer.setSize(innerWidth,innerHeight);renderer.setClearColor(0x020306,1);
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(38,innerWidth/innerHeight,.01,8000);
const composer=new EffectComposer(renderer);
composer.addPass(new RenderPass(scene,camera));
const bloom=new UnrealBloomPass(new THREE.Vector2(innerWidth,innerHeight),.85,.5,.24);
composer.addPass(bloom);composer.addPass(new OutputPass());

const THEMES=[['aether','#00d4ff'],['aurora','#f82a2a'],['ember','#e8843a'],['aurum','#f2c230'],['verdant','#2bd977']];
let themeIdx=0;
const BRAND=new THREE.Color(THEMES[0][1]);
const R=10;

function glowTexture(){const c=document.createElement('canvas');c.width=c.height=128;const g=c.getContext('2d');
  const gr=g.createRadialGradient(64,64,0,64,64,64);gr.addColorStop(0,'rgba(255,255,255,1)');gr.addColorStop(.2,'rgba(255,255,255,.55)');
  gr.addColorStop(.5,'rgba(255,255,255,.12)');gr.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=gr;g.fillRect(0,0,128,128);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t}
const GLOW=glowTexture();

// ═══════════════════════════════════════════════════════════════════════════
// 4. THE CORTEX — one organism. Its skin morphs: sphere / caduceus / iris / spores.
// ═══════════════════════════════════════════════════════════════════════════
const cortex=new THREE.Group();scene.add(cortex);
const NS=42000;
// regions: one per event family, painted onto the skin as swirls (video 2)
const NROOT=12,MAXREG=24; // shader slots: 12 territories, then up to 12 nested sectors
const regC=REG.map((d,i)=>{const v=fib(REG.length,i);v.applyAxisAngle(new V3(1,.3,0).normalize(),.6);return v.normalize()});
const domMax=Math.max(1,...REG.map(d=>M.domCounts[d]||0));
const regRad=REG.map(d=>(REG.length>8?.26:.3)+.34*Math.sqrt((M.domCounts[d]||0)/domMax));
const regBase=REG.map(d=>.12+.28*Math.sqrt((M.domCounts[d]||0)/domMax));
// pad the shader's 12 region slots (an empty slot has radius 0 and never matches)
const pad=(a,v,n=NROOT)=>{const o=a.slice();while(o.length<n)o.push(typeof v==='function'?v():v);return o};
// nested sectors sit inside their territory: a smaller cap, set toward one side, in a lighter shade of its colour
const subC=SUB.map((s,i)=>{const k=SUB.filter((q,j)=>j<i&&q.ri===s.ri).length,c=regC[s.ri],t1=new V3().crossVectors(c,new V3(0,1,.2)).normalize(),t2=new V3().crossVectors(c,t1);
  const a=k*2.4+s.ri,off=regRad[s.ri]*.42;return c.clone().addScaledVector(t1,Math.cos(a)*off).addScaledVector(t2,Math.sin(a)*off).normalize()});
const subRad=SUB.map(s=>regRad[s.ri]*clamp(.24+.5*Math.sqrt((s.members||1)/Math.max(1,M.domCounts[REG[s.ri]]||1)),.24,.4));
const subCol=SUB.map(s=>{const c=new THREE.Color(domCol(REG[s.ri]));const h={};c.getHSL(h);return c.setHSL((h.h+.05)%1,Math.min(1,h.s+.1),Math.min(.8,h.l+.12))});
const regSlots=(roots,subs,v)=>pad(roots,v).concat(pad(subs,v,MAXREG-NROOT));
const regAct=regBase.slice();

// session time axis for the caduceus
const sess=M.sessions;
const sT0=sess.length?sess[0].started:T0, sT1=nowS();
const sessS=s=>clamp((s.started-sT0)/Math.max(1,sT1-sT0),0,1);
// Caducean x along time, 0..1 (expand wide, compress narrow): each session's trajectory is laid
// over its own stretch of the axis, so the serpents widen and narrow with what the work did.
const expKnots=[];
sess.forEach(q=>{const s0=sessS(q),s1=q.ended?clamp((q.ended-sT0)/Math.max(1,sT1-sT0),0,1):1;
  q.traj.forEach((p,k)=>expKnots.push([lerp(s0,Math.max(s1,s0+.004),k/Math.max(1,q.traj.length-1)),clamp(.5+.5*p.x,0,1)]))});
expKnots.sort((a,b)=>a[0]-b[0]);
function expandAt(s){if(!expKnots.length)return .5;let lo=0,hi=expKnots.length-1;
  while(hi-lo>1){const m=(lo+hi)>>1;if(expKnots[m][0]<s)lo=m;else hi=m}
  const a=expKnots[lo],b=expKnots[hi];if(b[0]===a[0])return a[1];return lerp(a[1],b[1],clamp((s-a[0])/(b[0]-a[0]),0,1))}
const HELIX_H=1.75*R;
const helixY=s=>lerp(-HELIX_H,HELIX_H,s);

// oracle ordering: trusted first, then trying out, then watching (the iris reads as a ladder around the pupil)
const STATE_RANK={enforced:2,sampled:1,shadow:0};
// grouped by job (UX-PLAN 9.2), trusted first inside a job; up to MAXSEC sectors (16 hid 9 of 25 consumers)
const MAXSEC=32;
const JOB_ORDER=['route','approve','guard','interpret_step','judge_review','judge_step','judge_goal','judge_depth','shape','interpret','classify_event','judge_call'];
const jobRank=o=>{const i=JOB_ORDER.indexOf(o.job);return i<0?JOB_ORDER.length:i};
const ORC=M.oracle.slice().sort((a,b)=>(jobRank(a)-jobRank(b))||(STATE_RANK[b.state]-STATE_RANK[a.state])||(b.rows-a.rows)).slice(0,MAXSEC);
const NSEC=Math.max(1,ORC.length);
function barProgress(o){ // share of the bar met (MEMORY-DASHBOARD-DESIGN §8.1): rows, AUROC, precision, ECE
  if(o.state==='enforced')return 1;
  if(o.clauses){const ap=o.clauses.filter(c=>c.met!==null);return clamp(ap.filter(c=>c.met).length/Math.max(1,ap.length)*.95,.06,.95)}
  const p=[Math.min(1,o.rows/100),clamp((o.auroc-.5)/.15,0,1),clamp((o.precision||0)/.9,0,1),o.ece!=null?clamp((.12-o.ece)/.07,0,1):.5];
  return clamp(p.reduce((a,b)=>a+b,0)/p.length*.92,0.06,.95)}

const sPos=new Float32Array(NS*3),sHel=new Float32Array(NS*3),sIris=new Float32Array(NS*3),sCloud=new Float32Array(NS*3);
const sRand=new Float32Array(NS*4),sInfo=new Float32Array(NS*3);
for(let i=0;i<NS;i++){
  const v=fib(NS,i).multiplyScalar(R*(1+gauss()*.004));sPos.set([v.x,v.y,v.z],i*3);
  sRand.set([rng(),rng(),rng(),rng()],i*4);
  // caduceus: two serpents around a staff; width follows expand/compress over time
  const strand=i%11===0?2:(i%2);const s=rng();
  if(strand===2){sHel.set([gauss()*.05*R,helixY(s),gauss()*.05*R],i*3)}
  else{const ang=s*5*Math.PI*2+strand*Math.PI;const r=R*.6*(.45+.9*expandAt(s));
    sHel.set([Math.cos(ang)*r+gauss()*.035*R,helixY(s)+gauss()*.02*R,Math.sin(ang)*r+gauss()*.035*R],i*3)}
  // iris: radial wavy fibers, one sector per Oracle decision point
  const sec=i%NSEC, fpS=22, f=Math.floor(rng()*fpS), ft=Math.pow(rng(),.85);
  let th=(sec+(f+.5)/fpS)/NSEC*Math.PI*2+Math.PI/2;const ir=R*(.3+.75*ft);th+=.03*Math.sin(ir*1.3+f*1.7);
  sIris.set([Math.cos(th)*ir,Math.sin(th)*ir,R*.14*Math.pow(1-ft,2)+gauss()*.04],i*3);
  sInfo.set([sec,ft,strand],i*3);
  // spores: the skin exhales toward the artifact tissue (left of the orb)
  const cl=i%8, ca=cl/8*Math.PI*2;
  if(rng()<.7)sCloud.set([-2.3*R+Math.cos(ca)*.75*R+gauss()*.42*R,Math.sin(ca)*.75*R+gauss()*.42*R,gauss()*.25*R],i*3);
  else sCloud.set([-2.3*R+gauss()*1.3*R,gauss()*1.1*R,gauss()*.7*R],i*3);
}
const skinGeo=new THREE.BufferGeometry();
skinGeo.setAttribute('position',new THREE.BufferAttribute(sPos,3));
skinGeo.setAttribute('aHelix',new THREE.BufferAttribute(sHel,3));
skinGeo.setAttribute('aIris',new THREE.BufferAttribute(sIris,3));
skinGeo.setAttribute('aCloud',new THREE.BufferAttribute(sCloud,3));
skinGeo.setAttribute('aRand',new THREE.BufferAttribute(sRand,4));
skinGeo.setAttribute('aInfo',new THREE.BufferAttribute(sInfo,3));
const U={uTime:{value:0},uPix:{value:DPR}};
const skinMat=new THREE.ShaderMaterial({
  uniforms:{...U,uMH:{value:0},uMI:{value:0},uMC:{value:0},uBounce:{value:1},uWarn:{value:0},uShock:{value:0},
    uRegC:{value:regSlots(regC,subC,()=>new V3(0,1,0))},uRegCol:{value:regSlots(REG.map(d=>new THREE.Color(domCol(d))),subCol,()=>new THREE.Color())},uRegRad:{value:regSlots(regRad,subRad,0)},uRegAct:{value:regSlots(regAct,SUB.map(s=>regAct[s.ri]),0)},
    uHoverReg:{value:-1},uOpenReg:{value:-1},uOpen:{value:0},uBrand:{value:BRAND},uR:{value:R},
    uSecProg:{value:new Array(MAXSEC).fill(0)},uSecState:{value:new Array(MAXSEC).fill(0)},uSecPulse:{value:new Array(MAXSEC).fill(0)},uHoverSec:{value:-1},
    uScrollY:{value:0},uSkin:{value:1}},
  vertexShader:`
    uniform float uTime,uPix,uMH,uMI,uMC,uBounce,uWarn,uShock,uOpen,uR,uSkin;
    uniform int uHoverReg,uOpenReg,uHoverSec;
    uniform vec3 uRegC[${MAXREG}]; uniform vec3 uRegCol[${MAXREG}]; uniform float uRegRad[${MAXREG}]; uniform float uRegAct[${MAXREG}];
    uniform float uSecProg[32]; uniform float uSecState[32]; uniform float uSecPulse[32];
    uniform vec3 uBrand;
    attribute vec3 aHelix,aIris,aCloud; attribute vec4 aRand; attribute vec3 aInfo;
    varying vec3 vCol; varying float vA;
    float stag(float m,float r){return smoothstep(0.,1.,clamp(m*1.7-r*.7,0.,1.));}
    void main(){
      vec3 n=normalize(position);
      float mh=stag(uMH,aRand.x), mi=stag(uMI,aRand.y), mc=stag(uMC,aRand.z);
      vec3 p=position*uBounce;
      p=mix(p,aHelix,mh); p=mix(p,aIris,mi); p=mix(p,aCloud,mc);
      float tr=mh*(1.-mh)+mi*(1.-mi)+mc*(1.-mc);
      p+=vec3(sin(aRand.w*40.+uTime*.7),cos(aRand.x*37.+uTime*.6),sin(aRand.y*33.+uTime*.8))*tr*uR*.55;
      vec4 mv=modelViewMatrix*vec4(p,1.);
      float wS=(1.-mh)*(1.-mi)*(1.-mc), wH=mh*(1.-mi)*(1.-mc), wI=mi*(1.-mc), wC=mc;
      // ── sphere skin: fresnel (Aurora) + family swirls (video 2) + aperture
      vec3 nv=normalize(normalMatrix*n);
      float facing=abs(dot(nv,normalize(-mv.xyz)));
      float fres=pow(max(1.-facing,0.),2.2);
      vec3 col=vec3(.55,.66,.75); float reg=0.; float hole=1.;
      for(int i=0;i<${MAXREG};i++){
        float d=acos(clamp(dot(n,uRegC[i]),-1.,1.)); float rr=uRegRad[i];
        if(d<rr){
          // the skin only takes the region's colour; the pattern lives in the lattice cells
          float rn=d/rr;
          float act=uRegAct[i]+(uHoverReg==i?.9:0.);
          float w=(1.-smoothstep(.8,1.,rn))*(.22+min(act,1.)*.18);
          col=mix(col,uRegCol[i],clamp(w*1.6,0.,1.)); reg=max(reg,w*.6);
          if(i==uOpenReg){
            if(rn<uOpen*1.12) hole=0.;
            reg+=smoothstep(.08,0.,abs(rn-uOpen*1.12))*uOpen*2.; }
        }
      }
      col=mix(col,vec3(1.,.27,.22),uWarn*.5*fres);
      col=mix(col,vec3(1.),uShock*.6);
      float aS=(.016+.26*fres+reg*.5+uShock*.5)*hole*uSkin;
      float zS=1.+reg*1.3;
      // ── caduceus
      vec3 hc=aInfo.z<.5?uBrand:(aInfo.z<1.5?vec3(.82,.5,1.):vec3(.85,.9,.95));
      float aH=.2+.1*sin(uTime*1.5+aRand.w*30.);
      // ── iris
      int sec=int(aInfo.x+.5); float ft=aInfo.y;
      float prog=uSecProg[sec], st=uSecState[sec], pul=uSecPulse[sec];
      vec3 ic=st>1.5?uBrand:(st>.5?vec3(1.,.7,.28):vec3(.42,.52,.64));
      float lit=step(ft,prog);
      float flick=st>.5&&st<1.5?.65+.35*sin(uTime*5.+aRand.w*20.):1.;
      float ring=pul*smoothstep(.16,0.,abs(ft-(1.-pul)));
      float aI=mix(.022,st>1.5?.3:(st>.5?.2:.12),lit)*flick+ring*.55+(uHoverSec==sec?.14:0.);
      ic=mix(ic,vec3(1.),ring*.6);
      // ── spores
      vec3 cc=mix(vec3(.6,.75,.88),uBrand,.3); float aC=.12;
      vCol=col*wS+hc*wH+ic*wI+cc*wC;
      vA=aS*wS+aH*wH+aI*wI+aC*wC;
      float sz=zS*wS+.95*wH+(.85+lit*.3+ring*.6)*wI+1.3*wC;
      gl_PointSize=min(sz*uPix*(95./-mv.z),7.*uPix);
      gl_Position=projectionMatrix*mv;
    }`,
  fragmentShader:`varying vec3 vCol;varying float vA;
    void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;gl_FragColor=vec4(vCol,smoothstep(.5,0.,d)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const skin=new THREE.Points(skinGeo,skinMat);skin.frustumCulled=false;cortex.add(skin);

// Regions live IN the lattice: the same geodesic cells the wireframe draws. Shared GLSL finds the
// family region a direction belongs to (rw = membership, rc = colour, ra = activity, rn = 0 centre..1 rim).
const SU=skinMat.uniforms;
const impacts=Array.from({length:8},()=>new THREE.Vector4(0,1,0,-99)),impactCol=Array.from({length:8},()=>new THREE.Color());
let impactIx=0;
function impact(dir,col){impacts[impactIx].set(dir.x,dir.y,dir.z,clock.elapsedTime);impactCol[impactIx].set(col);impactIx=(impactIx+1)%8}
// immune response (Kyudo): one signed amplitude per territory slot. + = the region tightens and flickers briefly,
// - = it relaxes. Always decays to 0, so nothing ever builds up (see immuneSignal / the frame loop).
const IMM=new Array(MAXREG).fill(0);
const LATTICE_U={uRegC:SU.uRegC,uRegCol:SU.uRegCol,uRegRad:SU.uRegRad,uRegAct:SU.uRegAct,uHoverReg:SU.uHoverReg,uOpenReg:SU.uOpenReg,uOpen:SU.uOpen,
  uImp:{value:impacts},uImpCol:{value:impactCol},uImm:{value:IMM}};
const REGION_GLSL=`
  uniform vec3 uRegC[${MAXREG}]; uniform vec3 uRegCol[${MAXREG}]; uniform float uRegRad[${MAXREG}]; uniform float uRegAct[${MAXREG}]; uniform float uImm[${MAXREG}];
  uniform int uHoverReg,uOpenReg; uniform float uOpen; uniform vec4 uImp[8]; uniform vec3 uImpCol[8];
  // slots 12.. are nested sectors: they win inside their own cap (bias), so a child reads as its own patch inside its territory
  void region(vec3 n,out float rw,out vec3 rc,out float ra,out float rn,out float hole,out float rim){
    rw=0.;rc=vec3(0.);ra=0.;rn=1.;hole=1.;rim=0.;float best=0.;
    for(int i=0;i<${MAXREG};i++){if(uRegRad[i]<=0.)continue;float d=acos(clamp(dot(n,uRegC[i]),-1.,1.));float q=d/uRegRad[i];float sc=(1.-q)+(i>=${NROOT}?.4:0.);
      if(q<1.&&sc>best*.999){best=sc;rw=1.-q;rc=uRegCol[i];ra=uRegAct[i]+(uHoverReg==i?.9:0.);rn=q;}}
    if(uOpenReg>=0&&uOpenReg<${NROOT}){float d=acos(clamp(dot(n,uRegC[uOpenReg]),-1.,1.));float q=d/max(uRegRad[uOpenReg],.001);
      if(q<1.){if(q<uOpen*1.12)hole=0.;rim=smoothstep(.12,0.,abs(q-uOpen*1.12))*uOpen;}}
  }
  // the touched territory tightens (pulled toward its centre and pressed in about 1%); a negative amplitude relaxes it outward
  float immAmp(vec3 n){float s=0.;for(int i=0;i<${NROOT};i++){float a=uImm[i];if(a==0.||uRegRad[i]<=0.)continue;
      float q=acos(clamp(dot(n,uRegC[i]),-1.,1.))/uRegRad[i];s+=a*(1.-smoothstep(.35,1.,q));}return s;}
  vec3 immune(vec3 p){vec3 n=normalize(p);float r=length(p);float s=0.;vec3 pull=vec3(0.);
    for(int i=0;i<${NROOT};i++){float a=uImm[i];if(a==0.||uRegRad[i]<=0.)continue;
      float q=acos(clamp(dot(n,uRegC[i]),-1.,1.))/uRegRad[i];float w=1.-smoothstep(.35,1.,q);s+=a*w;pull+=(uRegC[i]-n)*a*w;}
    return normalize(n+pull*.035)*r*(1.-.013*s);}
  float ripples(vec3 n,float t,out vec3 col){float s=0.;col=vec3(0.);
    for(int k=0;k<8;k++){float age=t-uImp[k].w;if(age<0.||age>3.)continue;
      float ang=acos(clamp(dot(n,normalize(uImp[k].xyz)),-1.,1.));
      float q1=(ang-age*.75)/.06,q2=ang/.09;   // squared by hand: pow() of a negative base is NaN on most GPUs (the black-screen bug)
      float r=exp(-q1*q1)*exp(-age*1.3)+exp(-q2*q2)*exp(-age*5.);
      s+=r;col+=uImpCol[k]*r;}
    if(s>0.)col/=s;return s;}`;

// Aurora wireframe with travelling pulse bands; inside a region its lines take the family colour
const wireMat=new THREE.ShaderMaterial({
  uniforms:{...U,...LATTICE_U,uVis:{value:1},uWarn:{value:0},uShock:{value:0},uBrand:{value:BRAND},uR:{value:R}},
  vertexShader:`${REGION_GLSL}varying vec3 vP;varying float vI;void main(){vP=position;vI=immAmp(normalize(position));gl_Position=projectionMatrix*modelViewMatrix*vec4(immune(position),1.);}`,
  fragmentShader:`uniform float uTime,uVis,uWarn,uShock,uR;uniform vec3 uBrand;varying vec3 vP;varying float vI;${REGION_GLSL}
    void main(){vec3 n=normalize(vP);float lat=vP.y/uR;float lon=atan(vP.z,vP.x);float t=uTime*2.;
      float w1=sin(lat*5.2-t*1.5);float w2=sin(lon*3.+lat*2.+t*.8);
      float band=pow((w1*.7+w2*.3)*.5+.5,4.);
      float rw,ra,rn,hole,rim;vec3 rc;region(n,rw,rc,ra,rn,hole,rim);
      vec3 ic;float rp=ripples(n,uTime,ic);
      float inR=step(.0001,rw);
      vec3 pc=mix(uBrand,rc,inR*.85);pc=mix(pc,vec3(1.,.16,.16),uWarn);pc=mix(pc,ic,clamp(rp,0.,1.));pc=mix(pc,vec3(1.),uShock*.7);
      rp=min(rp,1.);
      // immune flicker: brief and small (at most about +14% at the strongest), dimmer while a region relaxes
      float fl=(1.+max(vI,0.)*.55*(.5+.5*sin(uTime*38.+vP.x*11.+vP.z*7.)))*(1.-max(-vI,0.)*.35);
      float br=(.06+band*.8+inR*(.12+ra*.12)+rp*.6+rim*1.6)*(1.+uShock*2.5)*fl;
      gl_FragColor=vec4(pc*br,(band*.24+.02+inR*(.07+ra*.04)+rp*.22+rim*.8+uShock*.3)*uVis*hole*fl);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,wireframe:true});
const wire=new THREE.Mesh(new THREE.IcosahedronGeometry(R*1.015,4),wireMat);cortex.add(wire);

// the cells themselves: each triangle of the lattice fills with its region's colour as one flat
// facet (the cell, not a gradient), glints when the region is busy, and carries event ripples.
const cellGeo=new THREE.IcosahedronGeometry(R*1.012,4);
// Each cell is a FRAGMENT (design §18): it stands a little apart from its neighbours and breathes. How tightly a
// territory's fragments hold together is its SYNC - the share of its claims that outside evidence has proven - so a
// well-proven territory reads as one assembled surface and a territory that is still learning drifts loose.
const regN=REG.map(d=>M.landmarks.filter(l=>l.domain===d).length);
const regSync=REG.map(d=>{let n=0,p=0;for(const l of M.landmarks)if(l.domain===d){n++;if(l.tier!=='candidate')p++}return (p+.5)/(n+1)});
{const p=cellGeo.attributes.position,n=p.count,fc=new Float32Array(n*3),fe=new Float32Array(n*3),fr=new Float32Array(n),fs=new Float32Array(n),a=new V3(),b=new V3(),c=new V3();
  for(let f=0;f<n;f+=3){a.fromBufferAttribute(p,f);b.fromBufferAttribute(p,f+1);c.fromBufferAttribute(p,f+2);const ce=a.clone().add(b).add(c).multiplyScalar(1/3),m=ce.clone().normalize(),r=rng();
    let best=0,sy=.5;regC.forEach((rc,i)=>{const q=Math.acos(clamp(m.dot(rc),-1,1))/regRad[i];if(q<1&&1-q>best){best=1-q;sy=regSync[i]}});
    for(let k=0;k<3;k++){fc.set([m.x,m.y,m.z],(f+k)*3);fe.set([ce.x,ce.y,ce.z],(f+k)*3);fr[f+k]=r;fs[f+k]=sy}}
  cellGeo.setAttribute('aFace',new THREE.BufferAttribute(fc,3));cellGeo.setAttribute('aCen',new THREE.BufferAttribute(fe,3));
  cellGeo.setAttribute('aR',new THREE.BufferAttribute(fr,1));cellGeo.setAttribute('aSync',new THREE.BufferAttribute(fs,1))}
const cellMat=new THREE.ShaderMaterial({
  uniforms:{...U,...LATTICE_U,uVis:wireMat.uniforms.uVis,uShock:wireMat.uniforms.uShock},
  vertexShader:`uniform float uTime,uVis,uShock;attribute vec3 aFace,aCen;attribute float aR,aSync;varying vec3 vC;varying float vA;${REGION_GLSL}
    void main(){vec3 n=normalize(aFace);float im=immAmp(n);
      float br=sin(uTime*1.14+aR*6.2832)*(.035+.03*(1.-aSync));                  // breathing, about 5.5 s; looser where sync is low
      vec3 q=aCen+(position-aCen)*(mix(.7,.9,aSync)+br)+n*length(aCen)*.012*(1.-aSync)*(.5+.5*sin(uTime*.31+aR*20.));
      vec4 mv=modelViewMatrix*vec4(immune(q),1.);
      float rw,ra,rn,hole,rim;vec3 rc;region(n,rw,rc,ra,rn,hole,rim);vec3 ic;float rp=ripples(n,uTime,ic);
      float inR=step(.0001,rw);
      vec3 nv=normalize(normalMatrix*n);float fres=pow(max(1.-abs(dot(nv,normalize(-mv.xyz))),0.),1.4);
      float glint=pow(.5+.5*sin(uTime*(.4+aR*1.2)+aR*60.),14.)*(.3+ra*.5);rp=min(rp,1.);
      float a=inR*(.028+ra*.022+glint*.05+step(.8,rn)*.025)+rp*.13+rim*.4+uShock*.06;
      vC=mix(mix(vec3(.55,.7,.8),rc,inR),ic,clamp(rp,0.,1.));
      vA=a*mix(.55,1.,aSync)*mix(.35,1.,fres)*hole*uVis*(1.+max(im,0.)*.55*(.5+.5*sin(uTime*37.+aR*50.)))*(1.-max(-im,0.)*.35);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`varying vec3 vC;varying float vA;void main(){gl_FragColor=vec4(vC,vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide});
const cells=new THREE.Mesh(cellGeo,cellMat);cortex.add(cells);

// inner core = what is on IRIS's mind right now (the aperture's contents orbit it)
const coreMat=new THREE.ShaderMaterial({
  uniforms:{uBrand:{value:BRAND},uGain:{value:1}},
  vertexShader:`varying vec3 vN;varying vec3 vV;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform vec3 uBrand;uniform float uGain;varying vec3 vN;varying vec3 vV;
    void main(){float f=max(dot(vN,vV),0.);float g=pow(f,5.5);gl_FragColor=vec4(uBrand*(g*1.25+.25)*uGain,(g*.85+.15)*min(uGain,1.));}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const core=new THREE.Mesh(new THREE.IcosahedronGeometry(R*.15,4),coreMat);cortex.add(core);
const coreHalo=new THREE.Sprite(new THREE.SpriteMaterial({map:GLOW,color:BRAND,transparent:true,opacity:.5,blending:THREE.AdditiveBlending,depthWrite:false}));
coreHalo.scale.setScalar(R*1.1);cortex.add(coreHalo);

// comet rings (Aurora) — their speed follows how busy the agent is
const rings=[];
[[1.55,.3,0,.6,1,4],[1.85,-.5,.4,.2,.6,3],[2.2,.2,-.7,-.3,1.4,5]].forEach(([rad,a,b,c,sp,tl])=>{
  const m=new THREE.ShaderMaterial({uniforms:{...U,uBrand:{value:BRAND},uSpeed:{value:sp},uVis:{value:.7},uTrail:{value:tl}},
    vertexShader:`varying float vAng;void main(){vAng=atan(position.y,position.x);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
    fragmentShader:`uniform float uTime,uSpeed,uVis,uTrail;uniform vec3 uBrand;varying float vAng;
      void main(){float w=sin(vAng+uTime*uSpeed*1.8)*.5+.5;float tr=pow(w,uTrail*3.);gl_FragColor=vec4(uBrand*(tr*1.7+.03),tr*uVis*.8);}`,
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
  const ring=new THREE.Mesh(new THREE.TorusGeometry(R*rad,R*.0055,8,320),m);ring.rotation.set(a,b,c);ring.userData.sp=sp;cortex.add(ring);rings.push(ring)});

// XurOrb signature: three 9-lobe epitrochoid shells (OrbCanvas.curvePoint), lifted into 3D.
// Each lobe rises and falls in depth, each curve is a thin tube of particles, and the three shells
// tumble on their own axes like a gyroscope. They are IRIS's attention: on a recall, a stream of
// shell particles peels off, reaches the recalled thought, and flows back (see tendrils below).
const XUR=[{scale:1.05,speed:1,count:220,alpha:.72},{scale:.70,speed:1.45,count:160,alpha:.55},{scale:.42,speed:.62,count:110,alpha:.95}];
const XTUBE=3;
XUR.forEach(s=>s.n=s.count*XTUBE);
const xurN=XUR.reduce((a,s)=>a+s.n,0);
const xurOff=new Float32Array(xurN*3);for(let i=0;i<xurN*3;i++)xurOff[i]=gauss();
const xurSpin=[new V3(0,1,.3).normalize(),new V3(1,.2,0).normalize(),new V3(.3,.4,1).normalize()];
const tendrils=[];
function reachOut(k){if(k<0||REDUCED&&tendrils.length)return;const si=Math.floor(rng()*3);
  tendrils.push({k,si,j0:Math.floor(rng()*XUR[si].count),n:Math.round(XUR[si].count*.22),t0:clock.elapsedTime})}
const xurPos=new Float32Array(xurN*3),xurA=new Float32Array(xurN);
const xurGeo=new THREE.BufferGeometry();
xurGeo.setAttribute('position',new THREE.BufferAttribute(xurPos,3));xurGeo.setAttribute('aA',new THREE.BufferAttribute(xurA,1));
const xurMat=new THREE.ShaderMaterial({uniforms:{...U,uBrand:{value:BRAND},uVis:{value:1}},
  vertexShader:`uniform float uPix;attribute float aA;varying float vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vA=aA;
    gl_PointSize=min(1.5*uPix*(95./-mv.z),5.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform vec3 uBrand;uniform float uVis;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    gl_FragColor=vec4(mix(uBrand,vec3(1.),.35),smoothstep(.5,0.,d)*vA*uVis);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const xur=new THREE.Points(xurGeo,xurMat);xur.frustumCulled=false;cortex.add(xur);
// THE ORACLE'S PUPIL (owner 2026-10-25: the XurOrb looked out of place in the iris; the centre needs its own form).
// The iris's fibres continue inward as rings of fine particles that turn against each other like the blades of an
// aperture and breathe. A live decision opens it: the outer band stops turning and its particles gather into one arc
// per offered option - arc length = probability, the chosen one bright - so the distribution is drawn by the pupil
// itself (UX-PLAN 9.1: d1 reads the answer from its scores). All motion is in the shader; the CPU sets uniforms only.
const PUPIL_N=1600;
const pR=new Float32Array(PUPIL_N),pU=new Float32Array(PUPIL_N),pS=new Float32Array(PUPIL_N),pRnd=new Float32Array(PUPIL_N);
for(let i=0;i<PUPIL_N;i++){const ring=Math.floor(rng()*7);pR[i]=clamp((ring+.25+rng()*.5)/7,0,1);pU[i]=rng();
  pS[i]=(ring%2?-1:1)*(.05+.03*ring)*(.85+rng()*.3);pRnd[i]=rng()}
const pupilGeo=new THREE.BufferGeometry();pupilGeo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(PUPIL_N*3),3));
pupilGeo.setAttribute('aR',new THREE.BufferAttribute(pR,1));pupilGeo.setAttribute('aU',new THREE.BufferAttribute(pU,1));
pupilGeo.setAttribute('aS',new THREE.BufferAttribute(pS,1));pupilGeo.setAttribute('aRnd',new THREE.BufferAttribute(pRnd,1));
const PU={uVis:{value:0},uDil:{value:1},uDec:{value:0},uRP:{value:R*.26},uArcA:{value:new Array(8).fill(0)},uArcB:{value:new Array(8).fill(0)},
  uArcOn:{value:new Array(8).fill(0)},uArcN:{value:0},uActed:{value:0}};
const pupilMat=new THREE.ShaderMaterial({uniforms:{...U,...PU,uBrand:{value:BRAND}},
  vertexShader:`uniform float uTime,uPix,uVis,uDil,uDec,uRP,uActed;uniform float uArcA[8],uArcB[8],uArcOn[8];uniform int uArcN;
    attribute float aR,aU,aS,aRnd;varying float vA;varying float vHot;
    void main(){
      float outer=step(.72,aR);
      float breath=1.+.05*sin(uTime*.55+aRnd*6.2832);
      float rad=(.16+.84*aR)*breath*uDil;
      float spin=aU*6.2832+uTime*aS;
      float hot=0.,inArc=0.;
      for(int i=0;i<8;i++){if(i>=uArcN)break;if(aU>=uArcA[i]&&aU<uArcB[i]){inArc=1.;hot=uArcOn[i];}}
      float d=uDec*outer;                                  // the outer band answers the decision
      float ang=mix(spin,aU*6.2832+1.5708,d);              // ... it stops turning and stands in its arc
      rad+=d*(.06+.08*hot);
      vec3 pos=vec3(cos(ang)*rad*uRP,sin(ang)*rad*uRP,(aRnd-.5)*uRP*.06);
      vec4 mv=modelViewMatrix*vec4(pos,1.);
      float a=mix(.22,.5,aR)*(.75+.25*sin(uTime*1.3+aRnd*9.));
      a=mix(a,inArc*(.28+.32*hot)+(1.-inArc)*.04,d);   // low glare: the arc reads by shape, not by blaze
      vA=a*uVis;vHot=d*hot*(.35+.25*uActed);
      gl_PointSize=min((1.3+.9*vHot)*uPix*(95./-mv.z),4.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform vec3 uBrand;varying float vA;varying float vHot;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    gl_FragColor=vec4(mix(mix(uBrand,vec3(1.),.25),vec3(1.),vHot),smoothstep(.5,0.,d)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const pupil=new THREE.Points(pupilGeo,pupilMat);pupil.frustumCulled=false;cortex.add(pupil);
// the pupil's live state: when the last decision came, its arcs, and the recent decisions (for its hover line)
const pupilLive={t:-9,recent:[]};
function pupilDecision(d){const ops=(d.options&&d.options.length?d.options:[{name:String(d.chosen??''),p:d.conf}]).slice(0,8);
  let cum=0;const gap=.012;ops.forEach((o,i)=>{const pv=clamp(+o.p||0,0,1);PU.uArcA.value[i]=cum+gap/2;PU.uArcB.value[i]=cum+Math.max(gap/2,pv-gap/2);
    PU.uArcOn.value[i]=String(o.name)===String(d.chosen)?1:.35;cum+=pv});PU.uArcN.value=ops.length;PU.uActed.value=d.acted?1:0;
  pupilLive.t=clock.elapsedTime;pupilLive.recent.push(nowS());if(pupilLive.recent.length>200)pupilLive.recent.shift()}
const xurPhase=[0,0,0];
const xurTilt=[new THREE.Euler(.5,.2,0),new THREE.Euler(-.4,.9,.3),new THREE.Euler(1.2,-.3,.5)];
const xurQ=xurTilt.map(e=>new THREE.Quaternion().setFromEuler(e));
const xurFlat=new THREE.Quaternion();
const xurV=new V3(),xurS=new V3(),xurC=new V3(),xurQt=new THREE.Quaternion();
function curvePoint(t,s){return [(7*Math.cos(t)-3*s*Math.cos(9*t))/10,(7*Math.sin(t)-3*s*Math.sin(9*t))/10]}

// ═══════════════════════════════════════════════════════════════════════════
// 5. the knowledge forest inside: landmarks as neurons (video 1), edges as axons
// ═══════════════════════════════════════════════════════════════════════════
const LM=M.landmarks;
const NL=LM.length;
// the objects of each kind of memory, so the key can single one kind out
const KIND_OBJ={claim:[],pin:[],moment:[],node:[]};
const CL=[...new Set(LM.map(l=>l.cls))];
const clDir=CL.map((c,i)=>fib(CL.length,i).multiplyScalar(R*.58));
// neurons fill the whole volume, leaning toward the skin region their knowledge belongs to
// Neurons are spread through the WHOLE ball (uniform in volume, radius 0.26R..0.92R), each leaning
// toward the skin region its knowledge belongs to, so the tissue reaches the outer structure.
const somaPos=LM.map(l=>{const fi=l.dom;
  const dir=regC[fi].clone().multiplyScalar(.9).add(clDir[CL.indexOf(l.cls)].clone().normalize().multiplyScalar(.35))
    .add(new V3(gauss(),gauss(),gauss()).multiplyScalar(.5)).normalize();
  const depth=lerp(Math.cbrt(rng()),1-syncClaim(l),.55);   // depth = sureness (UX-PLAN 7.2): surer = deeper
  return dir.multiplyScalar(R*(.26+.66*clamp(depth,0,1)))});
{ // relax: gentle springs on edges (long rest length, so links never pull the mass into the centre),
  // repulsion between all somas, stay inside the skin
  const E=M.edges.filter(e=>e.a<NL&&e.b<NL);const tmp=new V3();
  for(let it=0;it<24;it++){
    for(const e of E){const a=somaPos[e.a],b=somaPos[e.b];tmp.subVectors(b,a);const d=tmp.length()||1e-3;const f=(d-R*.32)*.006;tmp.multiplyScalar(f/d);a.add(tmp);b.sub(tmp)}
    for(let i=0;i<NL;i++)for(let j=i+1;j<NL;j++){const a=somaPos[i],b=somaPos[j];tmp.subVectors(b,a);const d=tmp.length()||1e-3;
      if(d<R*.15){tmp.multiplyScalar((R*.15-d)*.5/d);a.sub(tmp);b.add(tmp)}}
    for(const p of somaPos){const l=p.length();if(l>R*.92)p.multiplyScalar(R*.92/l);if(l<R*.22)p.multiplyScalar(R*.22/Math.max(l,1e-3))}
  }
}
const lmBest=LM.map(bestEvidence);
const iP=[],iSoma=[],iT=[],iRand=[],iCol=[],iBorn=[];
{
  const tmp=new THREE.Color();
  LM.forEach((l,si)=>{
    const S=somaPos[si];const born=clamp((l.born-T0)/Math.max(1,nowS()-T0),0,1);
    // each kind of knowledge has its own soft hue, so neighbouring neurons read as separate cells;
    // the nucleus keeps the evidence colour (the trust ladder)
    tmp.set(EVID_COL[lmBest[si]]||'#56707e');
    const hue=new THREE.Color().setHSL((CL.indexOf(l.cls)/Math.max(1,CL.length)+.52)%1,.55,.62);
    const push=(p,t)=>{iP.push(p.x,p.y,p.z);iSoma.push(si);iT.push(t);iRand.push(rng(),rng(),rng(),rng());
      const c=t<.001?tmp.clone():tmp.clone().lerp(hue,.55+Math.min(1,t)*.25);iCol.push(c.r,c.g,c.b);iBorn.push(born)};
    push(S,0);
  });
}
const NI=iSoma.length;
const forestGeo=new THREE.BufferGeometry();
forestGeo.setAttribute('position',new THREE.Float32BufferAttribute(iP,3));
forestGeo.setAttribute('aSoma',new THREE.Float32BufferAttribute(iSoma,1));
forestGeo.setAttribute('aT',new THREE.Float32BufferAttribute(iT,1));
forestGeo.setAttribute('aRand',new THREE.Float32BufferAttribute(iRand,4));
forestGeo.setAttribute('aCol',new THREE.Float32BufferAttribute(iCol,3));
forestGeo.setAttribute('aBorn',new THREE.Float32BufferAttribute(iBorn,1));
// per-soma live state, 2 texels each: (wake, helped-pulse, highlight, reach) (caution, candidate, focus, contradicted)
const somaData=new Float32Array(Math.max(1,NL)*2*4);
LM.forEach((l,i)=>{somaData[i*8+3]=l.tier==='candidate'?.42:1;somaData[i*8+5]=l.tier==='candidate'?1:0;somaData[i*8+7]=l.contradictions>0?1:0});
const somaTex=new THREE.DataTexture(somaData,Math.max(1,NL)*2,1,THREE.RGBAFormat,THREE.FloatType);
somaTex.minFilter=somaTex.magFilter=THREE.NearestFilter;somaTex.needsUpdate=true;
const forestU={...U,uSomaTex:{value:somaTex},uScrub:{value:1},uSearch:{value:0},uFocusDim:{value:0},uVis:{value:1},uNear:{value:0}};
const tierU={value:-1};   // -1 every claim, 1 proven only, 0 still learning only (the key)
const forestMat=new THREE.ShaderMaterial({uniforms:forestU,
  vertexShader:`
    uniform float uTime,uPix,uScrub,uSearch,uFocusDim,uVis; uniform sampler2D uSomaTex;
    attribute float aSoma,aT,aBorn; attribute vec4 aRand; attribute vec3 aCol;
    varying vec3 vCol; varying float vA;
    void main(){
      ivec2 ix=ivec2(int(aSoma+.5)*2,0);
      vec4 s0=texelFetch(uSomaTex,ix,0); vec4 s1=texelFetch(uSomaTex,ix+ivec2(1,0),0);
      float reach=s0.a; float vis=step(aT,reach+.001)*step(aBorn,uScrub);
      vec4 mv=modelViewMatrix*vec4(position,1.);
      float wake=s0.r,pulse=s0.g,hl=max(s0.b,s1.b);
      float ap=wake*pow(.5+.5*sin(aT*10.-uTime*7.+aRand.x*6.28),6.);
      float flick=mix(1.,.35+.65*abs(sin(uTime*(1.5+aRand.y*3.)+aRand.z*30.)),s1.g);
      float isCore=step(aT,.0001);
      float isMem=step(.005,aT)*step(aT,.03); // the cell membrane round the nucleus
      float base=mix(mix(.17-aT*.08,.1,isMem),0.,isCore)*flick; // the neuron body itself is the glyph layer
      float a=(base+wake*.55+ap*1.3+pulse*1.6*(1.-aT)+hl*.25)*(1.-isCore);
      a*=mix(1.,.12,uSearch*(1.-s0.b));
      a*=mix(1.,.38,uFocusDim*(1.-hl));
      vec3 col=aCol;
      float bad=clamp(s1.r+s1.a*step(.84,aRand.w)*(.5+.5*sin(uTime*6.+aRand.x*20.)),0.,1.);
      col=mix(col,vec3(1.,.3,.24),bad); col=mix(col,vec3(1.),pulse*.55+wake*.15);
      vCol=col; vA=a*vis*uVis;
      float sz=isCore>.5?(3.2+wake*3.+pulse*7.+hl*3.):(1.05+isMem*.5+ap*1.4);
      float cap=isCore>.5?(9.+pulse*12.+hl*6.):4.;
      gl_PointSize=min(sz*uPix*(70./-mv.z),cap*uPix);
      gl_Position=projectionMatrix*mv;
    }`,
  fragmentShader:`varying vec3 vCol;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    gl_FragColor=vec4(vCol,smoothstep(.5,0.,d)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const forest=new THREE.Points(forestGeo,forestMat);forest.frustumCulled=false;cortex.add(forest);KIND_OBJ.claim.push(forest);

// A CLAIM (landmark) is a CRYSTAL - one shape in the cortex, the corridor and every card (design §18; owner, 2026-10-19:
// "the visual representation of events, pins, landmarks are not properly identified"). Seen face-on it is a hexagon cut
// into six facets, still and sharp:
//   facets     = its evidence, one facet per share, by kind (white = you, green = tests / finished tasks,
//                cyan = held up again / a second source, grey = only IRIS's own word); each facet catches the light
//                at its own angle, so it reads as a cut stone, not a flat badge
//   the light inside = how much it is used · a thin outer hexagon = permanent
//   a claim still learning = only its outline, the facets barely there
//   contradicted = facets cracked red · the rim = the trust channel (Kyudo): a weak source leaves gaps in it
// It only ever dims - never brighter than a sealed, proven crystal.
const GLYPH_FRAG=`varying vec3 vC;varying float vA;varying vec4 vEv;varying vec4 vInfo;varying vec3 vHue;varying float vChan;
  void main(){vec2 p=(gl_PointCoord-.5)*2.;vec2 q=abs(p);float hx=max(q.x*.866+q.y*.5,q.y);if(hx>.96)discard;
    float cand=vInfo.x,perm=vInfo.y,bad=vInfo.z,use=vInfo.w,r=length(p);
    const float R0=.6;float inside=1.-smoothstep(R0-.015,R0+.005,hx);
    float ang=fract(atan(p.y,p.x)/6.2831853+1.+1./12.);float k=floor(ang*6.);float f=(k+.5)/6.;
    float e0=vEv.x,e1=e0+vEv.y,e2=e1+vEv.z;
    vec3 ec=f<e0?vec3(1.):(f<e1?vec3(.36,1.,.69):(f<e2?vec3(.5,.91,1.):vec3(.5,.6,.68)));
    float cr=step(k+.5,bad);ec=mix(ec,vec3(1.,.28,.22),cr);                          // the first n facets cracked red
    float shade=.5+.32*cos(f*6.2832-2.4);                                           // each facet catches the light differently
    float ridge=smoothstep(.022,0.,(.5-abs(fract(ang*6.)-.5))/6.*6.2832*r)*step(.05,r)*inside;   // the cut lines
    float crack=cr*smoothstep(.02,0.,abs(fract(r*7.+f*3.)-.5)*.12)*inside;
    float por=vChan<0.?0.:clamp((4.-vChan)/4.,0.,1.);
    float seg=floor(ang*18.),hh=fract(sin(seg*12.9898+vChan*3.1+use*78.233)*43758.5453),gap=step(1.-por*.85,hh);
    float rim=smoothstep(R0-.08,R0-.02,hx)*inside*(1.-gap*.9);
    float fill=mix(1.,.1,cand);
    float core=smoothstep(.1+.16*use,0.,r)*(.35+.65*use);                            // the light inside: use
    float pr=perm*smoothstep(.022,0.,abs(hx-.86))*.65;
    vec3 tint=vChan<0.?vec3(1.):mix(vec3(.66,.7,.92),vec3(1.,.96,.84),clamp(vChan/4.,0.,1.));
    vec3 rc=mix(mix(vHue,vec3(1.),.35),vC,.4)*tint;
    vec3 col=ec*shade*inside*fill*.5+ec*ridge*.5*fill+rc*rim*.95+mix(vC,vec3(1.),.5)*core*.75+vec3(.8,.9,1.)*pr+vec3(1.,.4,.3)*crack*.6;
    gl_FragColor=vec4(col,(inside*fill*.26*shade+ridge*.3*fill+rim*.8+core*.55+pr+crack*.4)*vA*(1.-por*.3));}`;
const KIND_HUE=cls=>new THREE.Color().setHSL((CL.indexOf(cls)/Math.max(1,CL.length)+.52)%1,.6,.62);
function glyphOf(i){const l=LM[i],c={};
  if(l.evidence_counts)Object.assign(c,l.evidence_counts);else l.evidence.forEach(e=>c[e.kind]=(c[e.kind]||0)+1);
  const g=[c.user||0,(c.test||0)+(c.completion||0),(c.recurrence||0)+(c.corroboration||0),(c.verifier||0)+(c.claim||0)+(c.none||0)];
  const s=g.reduce((a,b)=>a+b,0)||1;
  return {ev:g.map(v=>v/s),info:[l.tier==='candidate'?1:0,l.permanent?1:0,Math.min(3,l.contradictions||0),clamp(Math.log10(1+(l.activations||0))/2,0,1)],hue:KIND_HUE(l.cls)}}
const GLYPHS=LM.map((_,i)=>glyphOf(i));
// membrane colour per best evidence (the trust ladder); lighter than EVID_COL so faint kinds stay visible
const CELL_COL={user:'#f4fbff',recurrence:'#7fe8ff',corroboration:'#7fe8ff',test:'#5dffb0',completion:'#5dffb0',verifier:'#6fb3d6',claim:'#8aa3b0',none:'#6c7f8a'};
const cellSize=l=>l.tier==='candidate'?3.4:4.2+Math.min(3,Math.sqrt(l.activations||0)*.45);
const somaCellGeo=new THREE.BufferGeometry();
somaCellGeo.setAttribute('position',new THREE.Float32BufferAttribute(somaPos.flatMap(p=>[p.x,p.y,p.z]),3));
somaCellGeo.setAttribute('aSoma',new THREE.Float32BufferAttribute(LM.map((_,i)=>i),1));
somaCellGeo.setAttribute('aSize',new THREE.Float32BufferAttribute(LM.map(cellSize),1));
somaCellGeo.setAttribute('aBorn',new THREE.Float32BufferAttribute(LM.map(l=>clamp((l.born-T0)/Math.max(1,nowS()-T0),0,1)),1));
somaCellGeo.setAttribute('aCol',new THREE.Float32BufferAttribute(LM.flatMap((l,i)=>{const c=new THREE.Color(CELL_COL[lmBest[i]]||'#8aa3b0');return [c.r,c.g,c.b]}),3));
somaCellGeo.setAttribute('aEv',new THREE.Float32BufferAttribute(GLYPHS.flatMap(g=>g.ev),4));
somaCellGeo.setAttribute('aInfo',new THREE.Float32BufferAttribute(GLYPHS.flatMap(g=>g.info),4));
somaCellGeo.setAttribute('aHue',new THREE.Float32BufferAttribute(GLYPHS.flatMap(g=>[g.hue.r,g.hue.g,g.hue.b]),3));
somaCellGeo.setAttribute('aChan',new THREE.Float32BufferAttribute(LM.map(l=>l.channel==null?-1:l.channel),1));
const somaCellMat=new THREE.ShaderMaterial({uniforms:{...forestU,uTier:tierU},
  vertexShader:`uniform float uTime,uPix,uScrub,uSearch,uFocusDim,uVis,uNear,uTier;uniform sampler2D uSomaTex;
    attribute float aSoma,aSize,aBorn,aChan;attribute vec3 aCol,aHue;attribute vec4 aEv,aInfo;
    varying vec3 vC;varying float vA;varying vec4 vEv;varying vec4 vInfo;varying vec3 vHue;varying float vChan;
    void main(){vChan=aChan;ivec2 ix=ivec2(int(aSoma+.5)*2,0);vec4 s0=texelFetch(uSomaTex,ix,0),s1=texelFetch(uSomaTex,ix+ivec2(1,0),0);
      float hl=max(s0.b,s1.b);vec4 mv=modelViewMatrix*vec4(position,1.);
      float a=(.5+s0.r*.4+s0.g*.6+hl*.35)*mix(.35,1.,uNear)*mix(1.,.12,uSearch*(1.-s0.b))*mix(1.,.42,uFocusDim*(1.-hl))*step(aBorn,uScrub)*uVis*(uTier<0.?1.:step(abs((1.-s1.g)-uTier),.5));
      vC=mix(mix(aCol,vec3(1.),s0.g*.6),vec3(1.,.3,.24),s1.r);vA=a;vEv=aEv;vHue=aHue;
      vInfo=vec4(s1.g,aInfo.y,max(aInfo.z,s1.a*1.),aInfo.w); // live state wins: a promotion ends the dashes, a contradiction notches
      gl_PointSize=min(aSize*2.1*(1.+s0.g*.5+hl*.3)*uPix*(60./-mv.z),110.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:GLYPH_FRAG,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const somaCells=new THREE.Points(somaCellGeo,somaCellMat);somaCells.frustumCulled=false;cortex.add(somaCells);KIND_OBJ.claim.push(somaCells);

// a point on a quadratic curve a -> c -> b (sparks, threads and node tracts run along these)
function bez(a,c,b,t,out){const u=1-t;return out.set(u*u*a.x+2*u*t*c.x+t*t*b.x,u*u*a.y+2*u*t*c.y+t*t*b.y,u*u*a.z+2*u*t*c.z+t*t*b.z)}
// ── NEURON ARBORS (owner, 2026-10-19: "I still don't like how neurons look"). A claim's connections grow like FROST on
// glass: straight segments that fork at 60 degrees, thinner each generation - the crystal's own geometry carried
// outward, not hair. Every claim grows a small frost star round its crystal (more arms the more kinds of evidence it
// has) and sends one arm to its territory on the skin, where it lands on a lattice node and spreads along the lattice
// (the same path the sparks of section 6 run). Linked claims are joined by a frost bridge whose width is the link's
// standing score, firmed by use. A claim still learning has a shorter arbor (its reach). Light runs out along a claim's
// arbor when IRIS uses it, and along a bridge whose use grew since it was last seen.
const latticeV=(()=>{const p=wire.geometry.attributes.position,out=[],seen=new Set();for(let i=0;i<p.count;i++){const v=new V3().fromBufferAttribute(p,i);
  const k=v.x.toFixed(2)+','+v.y.toFixed(2)+','+v.z.toFixed(2);if(!seen.has(k)){seen.add(k);out.push(v.normalize())}}return out})();
const snap=dir=>{let best=latticeV[0],bd=-2;for(const v of latticeV){const d=v.dot(dir);if(d>bd){bd=d;best=v}}return best.clone().multiplyScalar(R*1.012)};
const somaAnchor=[],somaCtrl=[];
LM.forEach((l,i)=>{const fi=l.dom;
  const dir=regC[fi].clone().add(new V3(gauss(),gauss(),gauss()).multiplyScalar(regRad[fi]*.45)).normalize();
  const A=somaPos[i],B=snap(dir);
  somaAnchor.push(B.clone());somaCtrl.push(A.clone().lerp(B,.55).add(new V3(gauss(),gauss(),gauss()).multiplyScalar(R*.06)))});
const arborRes={value:new THREE.Vector2(innerWidth,innerHeight)};
const AR={pos:[],nx:[],side:[],t:[],w:[],ab:[],g:[],k:[],born:[],idx:[]};
const bornOf=i=>clamp((LM[i].born-T0)/Math.max(1,nowS()-T0),0,1);
// one straight segment as a screen-space ribbon (w in pixels); t = how far along its arbor (0 at the crystal)
function arSeg(A,B,tA,tB,w,ia,ib,g,kind,born){const base=AR.pos.length/3,d=B.clone().sub(A);
  for(const [P,t] of [[A,tA],[B,tB]])for(const sd of [-1,1]){AR.pos.push(P.x,P.y,P.z);AR.nx.push(d.x,d.y,d.z);AR.side.push(sd);AR.t.push(t);AR.w.push(w);
    AR.ab.push(ia,ib);AR.g.push(g);AR.k.push(kind);AR.born.push(born)}
  AR.idx.push(base,base+1,base+2,base+1,base+3,base+2)}
// frost: the segment, plus spurs that leave it at 60 degrees in the plane facing the core, alternating sides,
// each a shorter, thinner copy of the same rule
function frost(A,B,tA,tB,w,ia,ib,g,kind,born,depth){arSeg(A,B,tA,tB,w,ia,ib,g,kind,born);if(depth>=2)return;
  const D=B.clone().sub(A),len=D.length();if(len<R*.012)return;D.normalize();
  let n=A.clone().add(B).normalize();const perp=new V3().crossVectors(n,D);if(perp.lengthSq()<1e-6)perp.set(D.y,-D.x,0);perp.normalize();
  const nS=Math.min(3,Math.floor(len/(R*.035)));
  for(let s=0;s<nS;s++){const f=(s+.6+rng()*.3)/(nS+.4),P=A.clone().lerp(B,f),side=(s+depth)%2?1:-1;
    const dir=D.clone().multiplyScalar(.5).addScaledVector(perp,side*.866).normalize(),l=len*(.3+.15*rng())*(1-depth*.25);
    const t=lerp(tA,tB,f);frost(P,P.clone().addScaledVector(dir,l),t,t+(tB-tA)*.35,w*.6,ia,ib,g,kind,born,depth+1)}}
LM.forEach((l,i)=>{const S=somaPos[i],born=bornOf(i),cand=l.tier==='candidate';
  // the frost star round the crystal: arms = kinds of evidence (3 at least), in the plane facing the core
  const kinds=new Set(l.evidence.map(e=>e.kind)).size,arms=cand?3:clamp(3+kinds,3,6);
  const n=S.clone().normalize(),u=new V3().crossVectors(n,Math.abs(n.y)<.9?new V3(0,1,0):new V3(1,0,0)).normalize(),v=new V3().crossVectors(n,u),ph=rng()*6.283;
  for(let a=0;a<arms;a++){const th=ph+a/arms*6.2832,d=u.clone().multiplyScalar(Math.cos(th)).addScaledVector(v,Math.sin(th)).addScaledVector(n,(rng()-.5)*.4).normalize();
    const len=R*(.045+.03*Math.min(1,Math.log10(1+(l.activations||0))/2));frost(S.clone().addScaledVector(d,R*.012),S.clone().addScaledVector(d,len),0,.3,1,i,i,0,0,born,0)}
  // the arm to its territory: the spark path (soma -> ctrl -> anchor) in straight pieces, then along the lattice on the skin
  const A=S,C=somaCtrl[i],B=somaAnchor[i],K=7,pts=[];
  for(let k=0;k<=K;k++){const t=k/K,q=1-t;pts.push(new V3(q*q*A.x+2*q*t*C.x+t*t*B.x,q*q*A.y+2*q*t*C.y+t*t*B.y,q*q*A.z+2*q*t*C.z+t*t*B.z))}
  for(let k=0;k<K;k++)frost(pts[k],pts[k+1],k/K*.85,(k+1)/K*.85,1.25*(1-k/K*.45),i,i,0,0,born,k===K-1?2:1);
  // on the skin it spreads along two or three lattice edges from the node it landed on
  const Bn=B.clone().normalize(),near=latticeV.map(vv=>[vv.dot(Bn),vv]).filter(([dd])=>dd<.9999).sort((a,b)=>b[0]-a[0]).slice(0,3);
  near.forEach(([,vv],j)=>{if(j===2&&rng()<.5)return;arSeg(B,vv.clone().multiplyScalar(R*1.012).lerp(B,.35),.85,1,.8,i,i,0,0,born)})});
// bridges between linked claims: a frost bridge, width by the standing score firmed by use; light when its use grew
{const E=M.edges.filter(e=>e.a<NL&&e.b<NL);
  for(const e of E){const A=somaPos[e.a],B=somaPos[e.b],C=A.clone().add(B).multiplyScalar(.5*.78).add(new V3(gauss(),gauss(),gauss()).multiplyScalar(R*.04));
    const sc=clamp(e.score??.5,0,1),ev=clamp(Math.log10(1+(e.traversals||0))/1.8,0,1),body=(.3+.7*sc)*(.55+.45*ev),K=5,pts=[];
    for(let k=0;k<=K;k++){const t=k/K,q=1-t;pts.push(new V3(q*q*A.x+2*q*t*C.x+t*t*B.x,q*q*A.y+2*q*t*C.y+t*t*B.y,q*q*A.z+2*q*t*C.z+t*t*B.z))}
    const born=Math.max(bornOf(e.a),bornOf(e.b));
    for(let k=0;k<K;k++)frost(pts[k],pts[k+1],k/K,(k+1)/K,.4+1.2*body,e.a,e.b,e.grew?1:0,1,born,k===2&&body>.5?1:2)}}   // one frost knot mid-way on a strong bridge
// CROWDING: additive light sums where links overlap, so a dense knot burns white (measured on the live memory:
// 73 claims mostly in one territory, centre brightness 122 with 72 pure-white pixels). Taking the brightest value
// instead (MAX blending) fixed the knot but hid every single link wherever the haze behind it was brighter - the
// links vanished from inside the orb (owner, 2026-10-21). So the blending stays additive and each segment is dimmed
// by how crowded its neighbourhood is: a lone link keeps its full light, a knot of links shares one budget.
const AR_DEN=(()=>{const P=AR.pos,nSeg=P.length/12,h=R*.05,cell=new Map(),mid=new Float32Array(nSeg*3),den=new Float32Array(nSeg*4);
  const key=(x,y,z)=>Math.floor(x/h)+','+Math.floor(y/h)+','+Math.floor(z/h);
  for(let s_=0;s_<nSeg;s_++){const o=s_*12,x=(P[o]+P[o+6])/2,y=(P[o+1]+P[o+7])/2,z=(P[o+2]+P[o+8])/2;mid.set([x,y,z],s_*3);
    const k=key(x,y,z);let a=cell.get(k);if(!a)cell.set(k,a=[]);a.push(s_)}
  for(let s_=0;s_<nSeg;s_++){const x=mid[s_*3],y=mid[s_*3+1],z=mid[s_*3+2],cx=Math.floor(x/h),cy=Math.floor(y/h),cz=Math.floor(z/h);let n=0;
    for(let i=-1;i<=1;i++)for(let j=-1;j<=1;j++)for(let q=-1;q<=1;q++){const a=cell.get((cx+i)+','+(cy+j)+','+(cz+q));if(!a)continue;
      for(const t of a){const dx=mid[t*3]-x,dy=mid[t*3+1]-y,dz=mid[t*3+2]-z;if(dx*dx+dy*dy+dz*dz<h*h)n++}}
    den.fill(n,s_*4,s_*4+4)}
  return den})();
const arGeo=new THREE.BufferGeometry();
[['position',AR.pos,3],['aNx',AR.nx,3],['aSide',AR.side,1],['aT',AR.t,1],['aW',AR.w,1],['aAB',AR.ab,2],['aG',AR.g,1],['aK',AR.k,1],['aBorn',AR.born,1]]
  .forEach(([n,a,k])=>arGeo.setAttribute(n,new THREE.Float32BufferAttribute(a,k)));
arGeo.setAttribute('aDen',new THREE.Float32BufferAttribute(AR_DEN,1));
arGeo.setIndex(AR.pos.length/3>65535?new THREE.Uint32BufferAttribute(AR.idx,1):new THREE.Uint16BufferAttribute(AR.idx,1));
// brightness never builds up with the amount of memory: more bridges, each one dimmer
const uEdge={value:clamp(Math.sqrt(500/Math.max(1,M.edges.length)),.35,1)};
const arborMat=new THREE.ShaderMaterial({uniforms:{...U,uEdge,uRes:arborRes,uSomaTex:{value:somaTex},uSearch:forestU.uSearch,uVis:forestU.uVis,uFocusDim:forestU.uFocusDim,
    uNear:forestU.uNear,uScrub:forestU.uScrub,uBrand:{value:BRAND}},
  vertexShader:`uniform float uTime,uSearch,uFocusDim,uVis,uNear,uEdge,uScrub;uniform vec2 uRes;uniform sampler2D uSomaTex;
    attribute vec3 aNx;attribute float aSide,aT,aW,aG,aK,aBorn,aDen;attribute vec2 aAB;varying float vA,vH,vS,vRun;
    void main(){vec4 a0=texelFetch(uSomaTex,ivec2(int(aAB.x+.5)*2,0),0),b0=texelFetch(uSomaTex,ivec2(int(aAB.y+.5)*2,0),0);
      vec4 a1=texelFetch(uSomaTex,ivec2(int(aAB.x+.5)*2+1,0),0),b1=texelFetch(uSomaTex,ivec2(int(aAB.y+.5)*2+1,0),0);
      float hl=max(max(a0.b,b0.b),max(a1.b,b1.b)),wake=max(a0.r,b0.r);
      vec4 mv=modelViewMatrix*vec4(position,1.);vec4 c0=projectionMatrix*mv,c1=projectionMatrix*modelViewMatrix*vec4(position+aNx,1.);
      vec2 p0=c0.xy/max(c0.w,1e-4)*uRes*.5,p1=c1.xy/max(c1.w,1e-4)*uRes*.5,d=p1-p0;float sl=length(d);d=sl>1e-4?d/sl:vec2(1.,0.);
      c0.xy+=vec2(-d.y,d.x)*aW*(1.+hl*.2)*mix(.8,1.1,uNear)*aSide/(uRes*.5)*c0.w;
      float grown=aK>.5?1.:step(aT,a0.a+.001);                                     // a claim still learning has a shorter arbor
      float run=pow(fract(aT*1.4-uTime*.45+aAB.x*.37),14.)*(wake+aG*.7);            // light running out along it
      vRun=run;vH=hl;vS=aSide;
      vA=(.065+.04*aW)*grown*step(aBorn,uScrub)*(1.+hl*.9)*(1.+run*2.5)*mix(1.,.2,uSearch*(1.-max(a0.b,b0.b)))*mix(1.,.4,uFocusDim*(1.-hl))*uVis*uEdge*mix(.75,1.,uNear)*smoothstep(1.5,5.,-mv.z)*clamp(sqrt(6./max(aDen,1.)),.22,1.);   // a crowded knot shares one budget   // a branch right at your eye dissolves instead of crossing the view
      gl_Position=c0;}`,
  fragmentShader:`uniform vec3 uBrand;varying float vA,vH,vS,vRun;void main(){
    gl_FragColor=vec4(mix(mix(uBrand,vec3(.72,.88,1.),.55),vec3(1.),clamp(vH*.5+vRun*.6,0.,1.)),vA*(1.-vS*vS));}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide});
const arbors=new THREE.Mesh(arGeo,arborMat);arbors.frustumCulled=false;cortex.add(arbors);KIND_OBJ.claim.push(arbors);

// fragments: the 84k semantic pieces are a faint mist; the uncounted landmarks are dust
const mistN=7000,mP=new Float32Array(mistN*3),mR=new Float32Array(mistN);
for(let i=0;i<mistN;i++){const v=new V3(gauss(),gauss(),gauss()).normalize().multiplyScalar(R*Math.pow(rng(),.5)*.93);mP.set([v.x,v.y,v.z],i*3);mR[i]=rng()}
const mistGeo=new THREE.BufferGeometry();mistGeo.setAttribute('position',new THREE.BufferAttribute(mP,3));mistGeo.setAttribute('aR',new THREE.BufferAttribute(mR,1));
const mistMat=new THREE.ShaderMaterial({uniforms:{...U,uVis:forestU.uVis,uMist:{value:1}},
  vertexShader:`uniform float uTime,uPix,uVis,uMist;attribute float aR;varying float vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);
    vA=(.025+.035*sin(uTime*(.5+aR)+aR*40.))*uVis*uMist;gl_PointSize=min(1.2*uPix*(80./-mv.z),3.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`varying float vA;void main(){vec2 c=gl_PointCoord-.5;if(length(c)>.5)discard;gl_FragColor=vec4(.6,.75,.9,vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const mist=new THREE.Points(mistGeo,mistMat);mist.frustumCulled=false;cortex.add(mist);

// on-mind motes (CLM window / aperture): orbit the core; set-aside ones drift out
const motes=M.mind.slice(0,12).map((label,i)=>({label,state:i<9?'in':'out',r:i<9?R*.3:R*.55,rT:i<9?R*.3:R*.55,ang:rng()*6.28,
  axis:new V3(gauss(),gauss(),gauss()).normalize(),speed:rand(.15,.4),pos:new V3()}));
const moteGeo=new THREE.BufferGeometry();const moteP=new Float32Array(motes.length*3),moteA=new Float32Array(motes.length);
moteGeo.setAttribute('position',new THREE.BufferAttribute(moteP,3));moteGeo.setAttribute('aA',new THREE.BufferAttribute(moteA,1));
const moteMat=new THREE.ShaderMaterial({uniforms:{...U,uBrand:{value:BRAND}},
  vertexShader:`uniform float uPix;attribute float aA;varying float vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vA=aA;
    gl_PointSize=min(7.*uPix*(70./-mv.z),14.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform vec3 uBrand;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    gl_FragColor=vec4(mix(uBrand,vec3(1.),.6),(smoothstep(.16,.06,d)*.9+smoothstep(.5,0.,d)*.2)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const moteObj=new THREE.Points(moteGeo,moteMat);moteObj.frustumCulled=false;cortex.add(moteObj);

// caduceus beads: one per session, on the staff
// OUTSIDE CHAT (UX-PLAN 11.3): memory written under a thread that never was a chat conversation - voice with no chat
// open, probes, the system. Not a ghost (chat never had it), not a test run (those are left out of the snapshot).
const outsideChat=s=>!s.ghost&&!(s.messages||[]).length&&!/^test run/.test(s.objective||'');
const beadGeo=new THREE.BufferGeometry();const bP=new Float32Array(sess.length*3),bA=new Float32Array(sess.length),bS=new Float32Array(sess.length),bC=new Float32Array(sess.length*3);
sess.forEach((s,i)=>{bP.set([0,helixY(sessS(s)),0],i*3);bS[i]=(2.5+Math.sqrt(s.events.length)*.7)*(s.ghost?.7:1);
  // a ghost (chat deleted the strand; its tombstone keeps the name) stays on the helix, small and grey
  const c=new THREE.Color(s.ghost?'#4f5e68':s.exit==='live'?THEMES[0][1]:s.exit==='drift'?'#ffb547':outsideChat(s)?'#b9a98a':'#dfeaf2');bC.set([c.r,c.g,c.b],i*3)});
beadGeo.setAttribute('position',new THREE.BufferAttribute(bP,3));beadGeo.setAttribute('aA',new THREE.BufferAttribute(bA,1));
beadGeo.setAttribute('aDs',new THREE.BufferAttribute(Float32Array.from(sess,desyncSession),1));   // a session that failed or was set back desyncs
beadGeo.setAttribute('aS',new THREE.BufferAttribute(bS,1));beadGeo.setAttribute('aC',new THREE.BufferAttribute(bC,3));
// the timeline filter chips (UX-PLAN 8.3) DIM a strand that does not match, never remove it: 1 kept, 0 filtered out
const bF=new Float32Array(sess.length).fill(1);beadGeo.setAttribute('aF',new THREE.BufferAttribute(bF,1));
const beadMat=new THREE.ShaderMaterial({uniforms:{...U,uVis:{value:0},uHover:{value:-1}},
  vertexShader:`uniform float uPix,uVis,uTime;uniform float uHover;attribute float aA,aS,aDs,aF;attribute vec3 aC;varying vec3 vC;varying float vA;
    float h1(float x){return fract(sin(x*127.1)*43758.5453);}
    void main(){float id=float(gl_VertexID),dz=step(.9,h1(floor(uTime*5.)+id*7.3))*aDs;   // failures and setbacks: a brief glitch now and then
      vec4 mv=modelViewMatrix*vec4(position+vec3(h1(id+floor(uTime*20.))-.5,0.,h1(id*3.+floor(uTime*20.))-.5)*dz*.6,1.);float h=step(abs(id-uHover),.1);
      vC=mix(aC,vec3(1.,.3,.3),dz*.8);vA=uVis*(.8+aA*.6+h*.8)*mix(.16,1.,aF);
      gl_PointSize=min((aS+h*4.+aA*3.*(.5+.5*sin(uTime*3.)))*mix(.6,1.,aF)*uPix*(60./-mv.z),40.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
    float core=smoothstep(.22,.0,d),halo=smoothstep(.5,.0,d)*.4;gl_FragColor=vec4(vC,(core+halo)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
const beads=new THREE.Points(beadGeo,beadMat);beads.frustumCulled=false;cortex.add(beads);
// THREAD BRAIDS (UX-PLAN 4.3): a strand forked from a conversation hangs from it - a faint curved line from the parent's
// bead to each of its strands' beads that this memory holds.
const braidG=new THREE.Group();cortex.add(braidG);
{const P=[];const byId=new Map(sess.map(s=>[s.id,s]));
  for(const s of sess)for(const ch of s.strands||[]){const c=byId.get(ch.id);if(!c)continue;
    const a=new V3(0,helixY(sessS(s)),0),b=new V3(0,helixY(sessS(c)),0),m=a.clone().lerp(b,.5).add(new V3(R*.18,0,R*.18));
    const crv=new THREE.QuadraticBezierCurve3(a,m,b).getPoints(16);for(let i=0;i<crv.length-1;i++)P.push(crv[i].x,crv[i].y,crv[i].z,crv[i+1].x,crv[i+1].y,crv[i+1].z)}
  if(P.length){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(P,3));
    braidG.add(new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:0x7fe8ff,transparent:true,opacity:.28,blending:THREE.AdditiveBlending,depthWrite:false})))}}
// TURN ZOOM (UX-PLAN 8.4): Ctrl+wheel on the helix zooms in; then each conversation's bead opens into its turns - a
// short column of ticks beside it, one per turn (a user message and the reply after it). Hovering a tick reads that
// turn; clicking it walks into the conversation at that turn.
const TURNS=[];sess.forEach((s,si)=>{const ms=(s.messages||[]).slice().sort((a,b)=>a.ts-b.ts);let cur=null;
  for(const m of ms){if(m.role==='user'){cur={s,si,user:m,reply:null};TURNS.push(cur)}else if(cur&&!cur.reply)cur.reply=m}});
const turnsOf=new Map();TURNS.forEach(t=>{const a=turnsOf.get(t.si)||[];a.push(t);turnsOf.set(t.si,a)});
TURNS.forEach(t=>{const a=turnsOf.get(t.si),i=a.indexOf(t);t.world=new V3(R*.07,helixY(sessS(t.s))+(i-(a.length-1)/2)*R*.016,R*.07)});
const turnGeo=new THREE.BufferGeometry();turnGeo.setAttribute('position',new THREE.Float32BufferAttribute(TURNS.flatMap(t=>[t.world.x,t.world.y,t.world.z]),3));
const turnPts=new THREE.Points(turnGeo,new THREE.PointsMaterial({color:0xbfe9f6,size:3,sizeAttenuation:false,transparent:true,opacity:.85,depthWrite:false,blending:THREE.AdditiveBlending}));
turnPts.visible=false;turnPts.frustumCulled=false;cortex.add(turnPts);   // state.turnZoom is set per frame (state is declared below)
function turnHTML(t){const q=x=>{const v=String(x?.text||'').trim().split(/\n/)[0];return v.length>90?v.slice(0,89)+'…':v};
  return `<div class="k">turn ${fmt(turnsOf.get(t.si).indexOf(t)+1)} of ${fmt(turnsOf.get(t.si).length)} · ${ago(t.user.ts)}</div><div class="t">${esc(q(t.user)||'you wrote')}</div>
    <div class="m">${t.reply?`IRIS: <em>${esc(q(t.reply)||'replied')}</em>`:'no reply recorded'}<br>${esc(t.s.objective||'')}</div><span class="go">click · walk into this turn</span>`}
// DATE TICKS (UX-PLAN 4.3): now at the top, then today, yesterday, this week and the months; they slide with the helix
// like a clock face. LOD LABELS: the 4 newest conversations are named all the time; the rest on hover.
const TICKS=(()=>{const out=[],now=nowS(),d=new Date();d.setHours(0,0,0,0);const today=d.getTime()/1000;
  const add=(ts,w)=>{if(ts>=sT0&&ts<=sT1+60)out.push({ts,w})};add(now,'now');add(today,'today');add(today-86400,'yesterday');add(today-6*86400,'this week');
  const m=new Date(today*1000);m.setDate(1);for(let i=0;i<14;i++){const t=m.getTime()/1000;if(t<today-6*86400)add(t,m.toLocaleDateString('en-GB',{month:'short'}));m.setMonth(m.getMonth()-1)}
  return out})();
const tickEls=TICKS.map(t=>{const el=document.createElement('div');el.className='rlabel tick';el.textContent='— '+t.w;host.querySelector('#labels').appendChild(el);return el});   // labelsEl and $ are declared further down
// THREADS (UX-PLAN 4.1/4.4): a strand forked from another (chat parent_id, listed in the parent's `strands`) belongs to
// its parent's thread; the corridor's far door walks the strands of one thread in time.
const PARENT_OF=new Map();for(const s of sess)for(const c of s.strands||[])PARENT_OF.set(c.id,s.id);
const threadRoot=s=>{let id=s.id;for(let n=0;n<8&&PARENT_OF.has(id);n++)id=PARENT_OF.get(id);return id};
function nextInThread(s){const root=threadRoot(s);const mem=sess.filter(x=>threadRoot(x)===root).sort((a,b)=>a.started-b.started);
  const i=mem.indexOf(s);return i>=0&&i<mem.length-1?mem[i+1]:null}
const LOD=sess.filter(s=>!/^test run/.test(s.objective||'')).sort((a,b)=>b.started-a.started).slice(0,4);
const lodEls=LOD.map(s=>{const el=document.createElement('div');el.className='rlabel lod';const t=s.objective||'';el.textContent=t.length>34?t.slice(0,33)+'…':t;host.querySelector('#labels').appendChild(el);return el});
function placeTimelineLabels(show){
  braidG.visible=show;
  const right=new V3(1,0,0).applyQuaternion(camera.quaternion);let lastY=-1e9;
  TICKS.forEach((t,i)=>{const el=tickEls[i];if(!show){el.style.opacity=0;return}
    const a=project(new V3(0,timeY(t.ts),0).addScaledVector(right,-R*.62));
    if(!a.front||Math.abs(a.y-lastY)<16){el.style.opacity=0;return}lastY=a.y;
    el.style.opacity=.55;el.style.left=(a.x-el.offsetWidth)+'px';el.style.top=(a.y-7)+'px'});
  const used=[];   // newest conversations sit side by side: a name that would overlap another stays for hover
  LOD.forEach((s,i)=>{const el=lodEls[i];const k=sess.indexOf(s);if(!show||state.hoverBead===k||!bF[k]){el.style.opacity=0;return}
    const a=project(new V3(0,helixY(sessS(s)),0).addScaledVector(right,R*.32));
    if(!a.front||used.some(y=>Math.abs(y-a.y)<15)){el.style.opacity=0;return}used.push(a.y);el.style.opacity=.75;el.style.left=(a.x+6)+'px';el.style.top=(a.y-7)+'px'})}
sess.forEach((s,i)=>{if(s.exit==='live')bA[i]=1});
// TIMELINE FILTER CHIPS (UX-PLAN 8.3): by outcome and by territory (the strand's most common domain). One group = any
// of its chips; groups combine with AND. A strand that does not match dims (bF), never disappears. Chat tags are not a
// group: 5 of 5,836 conversations carry one (2026-10-26) - a chip row of them would filter nothing.
const sessOut=s=>s.exit==='live'?'live':s.exit==='drift'?'drifted':'finished';
const sessDom=sess.map(s=>{const c={};for(const e of s.events||[]){const d=e.domain||'general';c[d]=(c[d]||0)+1}
  return Object.entries(c).sort((a,b)=>b[1]-a[1])[0]?.[0]||'general'});
const filt={out:new Set(),dom:new Set()};
const CHIP_GROUPS=(()=>{const count=(xs)=>{const c={};for(const x of xs)c[x]=(c[x]||0)+1;return Object.entries(c).sort((a,b)=>b[1]-a[1])};
  return [['out',count(sess.map(sessOut))],['dom',count(sessDom).slice(0,6)]]
    .filter(([,xs])=>xs.length>1)})();   // a group with one value matches every strand: it filters nothing
function applyFilters(){const any=filt.out.size+filt.dom.size>0;
  sess.forEach((s,i)=>{bF[i]=!any||((!filt.out.size||filt.out.has(sessOut(s)))&&(!filt.dom.size||filt.dom.has(sessDom[i])))?1:0});
  beadGeo.attributes.aF.needsUpdate=true;renderChips()}
function renderChips(){const el=host.querySelector('#chips');if(!el)return;
  const n=sess.filter((_,i)=>bF[i]).length,any=filt.out.size+filt.dom.size>0;
  el.innerHTML=CHIP_GROUPS.map(([g,xs])=>xs.map(([v,c])=>`<a data-chip="${g}" data-v="${esc(v)}" class="${filt[g].has(v)?'on':''}">${esc(g==='dom'?domainWord(v):v)} <i>${fmt(c)}</i></a>`).join('')).join('<b>·</b>')+
    (any?`<b>·</b><a data-chipx>clear · ${fmt(n)} of ${fmt(sess.length)}</a>`:'')}
const domainWord=d=>(d||'general').replace(/_/g,' ');
host.querySelector('#chips')?.addEventListener('click',e=>{const x=e.target.closest('[data-chipx]');if(x){filt.out.clear();filt.dom.clear();applyFilters();return}
  const c=e.target.closest('[data-chip]');if(!c)return;const s=filt[c.dataset.chip];s.has(c.dataset.v)?s.delete(c.dataset.v):s.add(c.dataset.v);applyFilters()});
renderChips();

// ═══════════════════════════════════════════════════════════════════════════
// 5b. coordinate spaces as layers, the nodes in them (trust channel + fading), pins, the immune response
// ═══════════════════════════════════════════════════════════════════════════
// SPACES (mycelium_spaces): one faint shell per registered space, innermost = render_order 0, a space with no
// render order outermost. Its tint is its write lock: the lowest trust channel allowed to write there.
const SPACES=M.spaces.filter(s=>s.active!==false).sort((a,b)=>(a.render_order??99)-(b.render_order??99)||String(a.id).localeCompare(String(b.id))).slice(0,12);
const spR=SPACES.map((s,i)=>R*(.36+.5*(i+.5)/SPACES.length));
const spI=new Map(SPACES.map((s,i)=>[s.id,i]));
const spCol=SPACES.map((s,i)=>new THREE.Color().setHSL((.52+i*.11)%1,.45,.64));
const spaceU={uShow:{value:0}};
SPACES.forEach((s,i)=>{const m=new THREE.Mesh(new THREE.IcosahedronGeometry(spR[i],2),new THREE.ShaderMaterial({
  uniforms:{uShow:spaceU.uShow,uVis:forestU.uVis,uTint:{value:new THREE.Color(chanTint(s.write_lock)).lerp(spCol[i],.4)},uLock:{value:s.write_lock==null?2:s.write_lock}},
  vertexShader:`varying vec3 vN,vV;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`uniform float uShow,uVis,uLock;uniform vec3 uTint;varying vec3 vN,vV;
    void main(){float f=pow(max(1.-abs(dot(vN,vV)),0.),1.6);gl_FragColor=vec4(uTint,(.004+.012*f+uShow*(.03+.07*f))*(.55+.1*uLock)*uVis);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,wireframe:true}));cortex.add(m);KIND_OBJ.node.push(m)});

// NODES (mycelium_nodes): small cells on their space's shell. FADING (the 11 law, MEMORY-FOUNDATION-ANALYSIS 11.2):
// only confidence ABOVE the 0.4 floor was earned, so opacity and saturation follow (confidence-0.4)/0.6; what is not
// renewed sinks back to the floor and dims. Nothing here ever brightens with age. The membrane carries the trust channel.
const NDS=M.nodes.filter(n=>spI.has(n.space));
const nodePos=[],nodeSlot=new Map();
{const per=SPACES.map(()=>0),cnt=SPACES.map(()=>0);NDS.forEach(n=>per[spI.get(n.space)]++);
  const rot=SPACES.map((s,i)=>new THREE.Quaternion().setFromEuler(new THREE.Euler(i*1.3,i*2.1,i*.7)));
  NDS.forEach((n,j)=>{const si=spI.get(n.space);n.si=si;nodeSlot.set(M.nIndex.get(n.id),j);
    nodePos.push(fib(Math.max(1,per[si]),cnt[si]++).applyQuaternion(rot[si]).multiplyScalar(spR[si]*(1+gauss()*.012)))})}
const nodeGeo=new THREE.BufferGeometry();
nodeGeo.setAttribute('position',new THREE.Float32BufferAttribute(nodePos.flatMap(p=>[p.x,p.y,p.z]),3));
nodeGeo.setAttribute('aSize',new THREE.Float32BufferAttribute(NDS.map(n=>2.6+Math.min(2,Math.sqrt(n.used||0)*.35)),1));
nodeGeo.setAttribute('aConf',new THREE.Float32BufferAttribute(NDS.map(n=>n.conf),1));
nodeGeo.setAttribute('aChan',new THREE.Float32BufferAttribute(NDS.map(n=>n.chan==null?-1:n.chan),1));
nodeGeo.setAttribute('aBorn',new THREE.Float32BufferAttribute(NDS.map(n=>clamp((n.born-T0)/Math.max(1,nowS()-T0),0,1)),1));
nodeGeo.setAttribute('aCol',new THREE.Float32BufferAttribute(NDS.flatMap(n=>{const c=spCol[n.si];return [c.r,c.g,c.b]}),3));
const nodeMat=new THREE.ShaderMaterial({uniforms:{...U,uScrub:forestU.uScrub,uVis:forestU.uVis,uNear:forestU.uNear},
  vertexShader:`uniform float uPix,uScrub,uVis,uNear;attribute float aSize,aConf,aChan,aBorn;attribute vec3 aCol;
    varying vec3 vC;varying float vA,vChan,vF;
    void main(){vec4 mv=modelViewMatrix*vec4(position,1.);
      float f=smoothstep(0.,1.,clamp((aConf-.4)/.6,0.,1.));vF=f;vChan=aChan;
      vA=mix(.14,.58,f)*mix(.45,1.,uNear)*step(aBorn,uScrub)*uVis;
      vC=mix(vec3(dot(aCol,vec3(.33))),aCol,mix(.12,1.,f));
      gl_PointSize=min(aSize*uPix*(60./-mv.z),60.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`varying vec3 vC;varying float vA,vChan,vF;
    void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;float ang=fract(atan(c.x,-c.y)/6.2831853+1.);
      float por=vChan<0.?0.:clamp((4.-vChan)/4.,0.,1.);
      float seg=floor(ang*14.),hh=fract(sin(seg*12.9898+vF*78.233)*43758.5453);float gap=step(1.-por*.85,hh);
      float mem=smoothstep(.035,0.,abs(d-.3))*(1.-gap*.9);
      float leak=por*smoothstep(.02,0.,abs(d-.43))*step(.5,fract(ang*14.+.5))*.35;
      float body=smoothstep(.3,0.,d)*.3+smoothstep(.07,.03,d)*.6;
      vec3 tint=vChan<0.?vec3(1.):mix(vec3(.66,.7,.92),vec3(1.,.96,.84),clamp(vChan/4.,0.,1.));
      gl_FragColor=vec4(vC*tint*(mem*.9+body+leak),(mem*.8+body+leak*.6)*vA*(1.-por*.35));}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
if(NDS.length){const o=new THREE.Points(nodeGeo,nodeMat);o.frustumCulled=false;cortex.add(o);KIND_OBJ.node.push(o)}
// node tracts (mycelium_edges): thickness from score, firmed by evidence (observations / traversals)
{const ntP=[],ntW=[],P=new V3();
  for(const e of M.nodeEdges){const ia=nodeSlot.get(e.a),ib=nodeSlot.get(e.b);if(ia==null||ib==null)continue;
    const A=nodePos[ia],B=nodePos[ib],C=A.clone().add(B).multiplyScalar(.5*.8);
    const ev=clamp(Math.log10(1+Math.max(e.observations||0,e.traversals||0))/1.4,0,1),th=(.3+.7*clamp(e.score??.5,0,1))*(.45+.55*ev);
    const n=Math.round(10+26*th);
    for(let k=0;k<n;k++){const t=(k+rng())/n;bez(A,C,B,t,P);const r=R*(.0022+.004*th)*(.4+.6*Math.sin(t*Math.PI));
      ntP.push(P.x+gauss()*r,P.y+gauss()*r,P.z+gauss()*r);ntW.push(th)}}
  if(ntP.length){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(ntP,3));g.setAttribute('aTh',new THREE.Float32BufferAttribute(ntW,1));
    const o=new THREE.Points(g,new THREE.ShaderMaterial({uniforms:{...U,uVis:forestU.uVis,uNear:forestU.uNear},
      vertexShader:`uniform float uPix,uVis,uNear;attribute float aTh;varying float vA;
        void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vA=(.03+.2*aTh)*mix(.45,1.,uNear)*uVis;
          gl_PointSize=min((.9+1.1*aTh)*uPix*(70./-mv.z),4.*uPix);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;gl_FragColor=vec4(.62,.78,.88,smoothstep(.5,0.,d)*vA);}`,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));o.frustumCulled=false;cortex.add(o);KIND_OBJ.node.push(o)}}

// PINS (mycelium_pins): explicit memory, held not earned (it does not fade by the 11 law). A shard in brackets just inside
// the wall of its territory (its nested sector when it has one), pin-type colour, size by link count. Taut straight
// tethers run to what it references; held in context = it breathes in its brackets. None when the store has none.
// A PIN is a small shard held between two BRACKETS that always face you: held, not earned - it does not drift or fade.
// Its colour is its pin type; a pin held in context right now breathes slowly in its brackets.
const pinH={value:innerHeight*.5};
const PIN_VS=`uniform float uTime,uPix,uVis,uH;attribute vec3 aCol;attribute float aHeld,aSize;varying vec3 vC;varying float vA,vH;
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float z=max(-mv.z,.1);vC=aCol;vH=aHeld;vA=uVis*smoothstep(.2,1.,z);
    gl_PointSize=clamp(aSize*projectionMatrix[1][1]*uH/z,5.*uPix,26.*uPix);gl_Position=projectionMatrix*mv;}`;
const PIN_FRAG=`uniform float uTime;varying vec3 vC;varying float vA,vH;
  void main(){vec2 p=(gl_PointCoord-.5)*2.;vec2 q=abs(p);
    float hx=max(q.x*.866+q.y*.5,q.y),shard=1.-smoothstep(.36,.4,hx),edge=smoothstep(.28,.36,hx)*shard;
    float facet=step(0.,p.x*p.y);                                                   // two lit facets, two in shade
    float bar=smoothstep(.06,.0,abs(q.x-.8))*step(q.y,.66),arm=smoothstep(.06,0.,abs(q.y-.64))*step(.62,q.x)*step(q.x,.84);
    float br=max(bar,arm),pulse=1.+vH*.4*sin(uTime*1.3);
    vec3 col=vC*shard*(.3+.18*facet)+mix(vC,vec3(1.),.4)*edge*.7+mix(vC,vec3(1.),.55)*br*.85*pulse;
    gl_FragColor=vec4(col*.8,(shard*.26+edge*.4+br*.5*pulse)*vA);}`;
function pinSprites(list,uVis){ // list: {pos,col,held,s}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(list.flatMap(c=>[c.pos.x,c.pos.y,c.pos.z]),3));
  g.setAttribute('aCol',new THREE.Float32BufferAttribute(list.flatMap(c=>[c.col.r,c.col.g,c.col.b]),3));
  g.setAttribute('aHeld',new THREE.Float32BufferAttribute(list.map(c=>c.held),1));g.setAttribute('aSize',new THREE.Float32BufferAttribute(list.map(c=>c.s*2.8),1));
  return Object.assign(new THREE.Points(g,new THREE.ShaderMaterial({uniforms:{...U,uVis,uH:pinH},vertexShader:PIN_VS,fragmentShader:PIN_FRAG,
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false,renderOrder:3})}
const PINS=M.pins.slice(0,80);let pinArtTethers=null;const pinTethers=[];
const cloudPt=id=>{let h=7;for(const ch of String(id))h=(h*31+ch.charCodeAt(0))>>>0;const r=mulberry32(h);return new V3(-2.3*R+(r()-.5)*1.6*R,(r()-.5)*1.6*R,(r()-.5)*.8*R)};
const pinInfo=PINS.map(p=>{const ri=REGI[p.domain]??0;let c=regC[ri],rad=regRad[ri];
  if(p.sector&&SUBI[p.sector]!=null){c=subC[SUBI[p.sector]];rad=subRad[SUBI[p.sector]]}
  const dir=c.clone().add(new V3(gauss(),gauss(),gauss()).multiplyScalar(rad*.45)).normalize(),s=R*(.02+.011*Math.sqrt(Math.max(1,p.links||1)));
  const base=dir.clone().multiplyScalar(R*.985);
  return {p,dir,base,s,tip:base.clone().addScaledVector(dir,-s*2.0),col:new THREE.Color(pinType(p.type).col),held:p.held?1:0}});
if(PINS.length){
  const pinObj=pinSprites(pinInfo.map(q=>({pos:q.tip,col:q.col,held:q.held,s:q.s})),forestU.uVis);cortex.add(pinObj);KIND_OBJ.pin.push(pinObj);
  // tethers: straight from the tip to what the pin references (a certainty, a node, a thing made)
  // (a tether to a thing made reaches out of the orb to where the artifact tissue settles, so it shows in that lens only)
  const tp=[],tc=[],ap=[],ac=[];
  for(const q of pinInfo)for(const r of q.p.refs){let to=null,art=false;
    if(r.t==='landmark'){const k=M.lmIndex.get(r.id);if(k!=null)to=somaPos[k]}
    else if(r.t==='node'){const k=nodeSlot.get(M.nIndex.get(r.id));if(k!=null)to=nodePos[k]}
    else if(r.t==='artifact'||r.t==='document'){to=cloudPt(r.id);art=true}
    if(!to)continue;const f=q.held?.3:.12,P=art?ap:tp,Cc=art?ac:tc;
    P.push(q.tip.x,q.tip.y,q.tip.z,to.x,to.y,to.z);Cc.push(q.col.r*f,q.col.g*f,q.col.b*f,q.col.r*f*.6,q.col.g*f*.6,q.col.b*f*.6)}
  const tether=(P,Cc)=>{if(!P.length)return null;const g_=new THREE.BufferGeometry();g_.setAttribute('position',new THREE.Float32BufferAttribute(P,3));g_.setAttribute('color',new THREE.Float32BufferAttribute(Cc,3));
    const l=new THREE.LineSegments(g_,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false}));l.frustumCulled=false;cortex.add(l);return l};
  const t1=tether(tp,tc);if(t1){pinTethers.push(t1);KIND_OBJ.pin.push(t1)}
  pinArtTethers=tether(ap,ac);if(pinArtTethers){pinArtTethers.visible=false;pinTethers.push(pinArtTethers)}}
const pinHTML=k=>{const p=PINS[k],t=pinType(p.type),th=p.refs.filter(r=>r.t==='thread'||r.t==='session').length;
  return `<div class="k">pin · ${t.word} · ${p.held?'held in context right now':'resting'}${p.permanent?' · permanent':''}</div><div class="t">${esc(p.title)}</div>
    <div class="m">tied to <em>${p.links}</em> thing${p.links===1?'':'s'}${th?` · used in <em>${th}</em> thread${th===1?'':'s'}`:''} · pinned ${ago(p.created)}<br>pins do not fade: they are held, not earned</div>`};
const nodeHTML=k=>{const n=NDS[k],sp=SPACES[n.si],f=clamp((n.conf-.4)/.6,0,1);
  return `<div class="k">node · ${esc(SPACE_WORD[sp.id]||sp.id)} · ${esc(chanWord(n.chan))}</div><div class="t">${esc(n.label?nodeWord(n.label):SPACE_WORD[sp.id]||sp.id)}</div>
    <div class="m">how sure IRIS is: <em>${Math.round(n.conf*100)}%</em> · ${f<.02?'on the floor it was given: nothing has earned it more':'earned above the floor'}<br>used <em>${fmt(n.used||0)}</em> times${sp.write_lock!=null?`<br>${esc(LOCK_WORD[sp.write_lock]||'')}`:''}</div>`};

// IMMUNE RESPONSE (Kyudo, mycelium_quorum_log): a live signal = a brief, small tightening + flicker of the territory it
// touched; a shadow signal (measured, never counted) = only a faint mark that fades; a reorganization reset = the
// territory relaxing. Amplitudes only ever decay toward 0 (see the frame loop), so nothing builds up over time.
const MARKN=24,markP=new Float32Array(MARKN*3),markA=new Float32Array(MARKN),marks=Array.from({length:MARKN},()=>({t0:-999}));
const markGeo=new THREE.BufferGeometry();markGeo.setAttribute('position',new THREE.BufferAttribute(markP,3));markGeo.setAttribute('aA',new THREE.BufferAttribute(markA,1));
const marksObj=new THREE.Points(markGeo,new THREE.ShaderMaterial({uniforms:{...U},
  vertexShader:`uniform float uPix;attribute float aA;varying float vA;void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vA=aA;
    gl_PointSize=min(7.*uPix*(95./-mv.z),12.*uPix);gl_Position=projectionMatrix*mv;}`,
  fragmentShader:`varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);gl_FragColor=vec4(.66,.74,.8,(smoothstep(.04,0.,abs(d-.32))*.8+smoothstep(.08,.02,d)*.5)*vA);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));marksObj.frustumCulled=false;cortex.add(marksObj);
function addMark(p){const m=marks.reduce((a,b)=>a.t0<b.t0?a:b);m.t0=clock.elapsedTime;const i=marks.indexOf(m);markP.set([p.x,p.y,p.z],i*3)}
function updateMarks(t){for(let i=0;i<MARKN;i++){const age=t-marks[i].t0,life=26;markA[i]=age<0||age>life?0:Math.min(1,age/1.2)*(1-age/life)*.16}
  markGeo.attributes.aA.needsUpdate=markGeo.attributes.position.needsUpdate=true}
function quorumRegion(q){if(q.landmark!=null){const k=M.lmIndex.get(q.landmark);if(k!=null)return LM[k].dom}
  const s=q.session&&M.sById.get(q.session);return s?regOf(s.domain):-1}
function setImm(ri,a){const set=(i,v)=>{IMM[i]=v>0?Math.max(IMM[i],v):Math.min(IMM[i],v)};
  if(ri>=0)set(ri,a);else for(let i=0;i<REG.length;i++)set(i,a*.5)} // no known territory: the whole lattice, at half strength
function immuneSignal(q){const ri=quorumRegion(q);tickGuard(q,ri);
  if(q.signal==='quorum_reorganization_reset')setImm(ri,-.5);
  else if(q.shadow){if(ri>=0)addMark(regionPoint(ri))}
  else setImm(ri,clamp(.2+.8*(q.weight||.15),.2,.55)*(REDUCED?.5:1))}


// ═══════════════════════════════════════════════════════════════════════════
// 6. impulses: sparks (action potentials), pulse rings, recall threads, shockwave
// ═══════════════════════════════════════════════════════════════════════════
const SPK=56,SSEG=16;
const spkPos=new Float32Array(SPK*SSEG*2*3),spkCol=new Float32Array(SPK*SSEG*2*3);
const spkGeo=new THREE.BufferGeometry();
spkGeo.setAttribute('position',new THREE.BufferAttribute(spkPos,3));spkGeo.setAttribute('color',new THREE.BufferAttribute(spkCol,3));
const sparkLines=new THREE.LineSegments(spkGeo,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false}));
sparkLines.frustumCulled=false;scene.add(sparkLines);
const headPos=new Float32Array(SPK*3),headCol=new Float32Array(SPK*3);
const headGeo=new THREE.BufferGeometry();headGeo.setAttribute('position',new THREE.BufferAttribute(headPos,3));headGeo.setAttribute('color',new THREE.BufferAttribute(headCol,3));
const heads=new THREE.Points(headGeo,new THREE.PointsMaterial({size:R*.045,map:GLOW,vertexColors:true,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false}));
heads.frustumCulled=false;scene.add(heads);KIND_OBJ.moment.push(sparkLines,heads);
const sparks=Array.from({length:SPK},()=>({on:false,a:new V3(),b:new V3(),c:new V3(),t:0,sp:1,col:new THREE.Color(),gain:1,done:null,jit:.05}));
function spark(a,b,col,{speed=.8,gain=1,done=null,bend=.5,jit=.05,ctrl=null}={}){
  const s=sparks.find(x=>!x.on);if(!s)return;
  s.on=true;s.a.copy(a);s.b.copy(b);
  if(ctrl)s.c.copy(ctrl);else{s.c.addVectors(a,b).multiplyScalar(.5);s.c.multiplyScalar(bend).add(new V3(gauss(),gauss(),gauss()).multiplyScalar(R*.08))}
  s.t=0;s.sp=speed*(REDUCED?.5:1);s.col.set(col);s.gain=gain;s.done=done;s.jit=jit}
function updateSparks(dt){
  const P=new V3(),Q=new V3();
  sparks.forEach((s,i)=>{
    const base=i*SSEG*2*3;
    if(!s.on){spkPos.fill(0,base,base+SSEG*6);spkCol.fill(0,base,base+SSEG*6);headCol.fill(0,i*3,i*3+3);return}
    s.t+=dt*s.sp;
    const head=Math.min(s.t,1),fade=s.t>1?Math.max(0,1-(s.t-1)*3):1;
    let prev=null;
    for(let k=0;k<=SSEG;k++){
      const u=clamp(head-k*.022,0,1);bez(s.a,s.c,s.b,u,P);
      if(k>0)P.add(new V3(gauss(),gauss(),gauss()).multiplyScalar(R*s.jit*.12));
      if(prev&&k<=SSEG){const o=base+(k-1)*6,I=Math.pow(1-k/SSEG,1.6)*s.gain*fade*1.6;
        spkPos.set([prev.x,prev.y,prev.z,P.x,P.y,P.z],o);
        spkCol.set([s.col.r*I,s.col.g*I,s.col.b*I,s.col.r*I*.8,s.col.g*I*.8,s.col.b*I*.8],o)}
      prev=P.clone();
    }
    bez(s.a,s.c,s.b,head,Q);headPos.set([Q.x,Q.y,Q.z],i*3);
    headCol.set([s.col.r*s.gain*fade,s.col.g*s.gain*fade,s.col.b*s.gain*fade],i*3);
    if(s.t>=1&&s.done){const d=s.done;s.done=null;d()}
    if(s.t>1.35)s.on=false;
  });
  spkGeo.attributes.position.needsUpdate=spkGeo.attributes.color.needsUpdate=true;
  headGeo.attributes.position.needsUpdate=headGeo.attributes.color.needsUpdate=true;
}
const pulseRings=Array.from({length:14},()=>{const m=new THREE.Mesh(new THREE.RingGeometry(.92,1,96),
  new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide}));
  m.visible=false;scene.add(m);return {m,t:0,dur:1,max:1,on:false}});
function pulseRing(pos,col,size,dur=1.4){const p=pulseRings.find(x=>!x.on);if(!p)return;p.on=true;p.t=0;p.dur=dur;p.max=size;p.m.position.copy(pos);
  p.m.material.color.set(col);p.m.visible=true}
function updateRings(dt){for(const p of pulseRings){if(!p.on)continue;p.t+=dt;const x=p.t/p.dur;if(x>=1){p.on=false;p.m.visible=false;continue}
  p.m.scale.setScalar(p.max*(.15+easeIO(Math.min(1,x*1.3))*.85));p.m.material.opacity=Math.pow(1-x,1.6)*.9;p.m.lookAt(camera.position)}}
const threads=Array.from({length:6},()=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(40*3),3));
  const l=new THREE.Line(g,new THREE.LineBasicMaterial({color:0xffffff,transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false}));
  l.frustumCulled=false;scene.add(l);return {l,t:0,life:0,on:false,a:new V3(),b:new V3(),c:new V3()}});
function thread(a,b,col,life=4){const th=threads.find(x=>!x.on)||threads[0];th.on=true;th.t=0;th.life=life;th.a.copy(a);th.b.copy(b);
  th.c.addVectors(a,b).multiplyScalar(.5).multiplyScalar(.6);th.l.material.color.set(col);
  const arr=th.l.geometry.attributes.position.array,P=new V3();for(let k=0;k<40;k++){bez(th.a,th.c,th.b,k/39,P);arr.set([P.x,P.y,P.z],k*3)}
  th.l.geometry.attributes.position.needsUpdate=true;return th}
function updateThreads(dt){for(const th of threads){if(!th.on)continue;th.t+=dt;const x=th.t/th.life;if(x>=1){th.on=false;th.l.material.opacity=0;continue}
  th.l.material.opacity=Math.min(1,th.t*3)*(1-x)*.8}}
const shockMat=new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false});
const shockMesh=new THREE.Mesh(new THREE.TorusGeometry(R,R*.006,12,256),shockMat);shockMesh.visible=false;cortex.add(shockMesh);
let shockT=-10;
function shockwave(){shockT=clock.elapsedTime;shockMesh.visible=true}
function shockAt(el){const d=el-shockT,D=1.2;if(d<0||d>D)return 0;const x=d/D;if(x<.08)return x/.08;return Math.exp(-(x-.08)/.92*4)}
function bounceAt(el){const d=el-shockT,D=1.2;if(d<0||d>D)return 1;const x=d/D;return 1+Math.exp(-x*6)*Math.sin(x*Math.PI*4)*.06}

// ═══════════════════════════════════════════════════════════════════════════
// 7. a session = its own dimension: a MEMORY CORRIDOR you relive (design §18). It assembles out of hex fragments
//    around you; the conversation (conversations.db) and the memory (memory.db) run through it as one double strand,
//    with a rung wherever a moment belongs to a turn. Messages and moments are shard fragments on their strand (a
//    strong source is solid, a weak one only its edge), claims are the glyph, pins are locked crystals, and where the
//    work failed the corridor desyncs. The far end is a tall soft arch the strands climb onto.
// ═══════════════════════════════════════════════════════════════════════════
const TUN_OFF=new V3(0,0,-3000);
const UP=new V3(0,1,0);   // world up: the corridor runs along -z, so it is never parallel to the view
let tunnel=null;
const THREAD_COL=new THREE.Color('#c23aa8'),STRAND_COL=new THREE.Color('#e070d0');
// conversations.db rows when the snapshot has them; otherwise the turns the events imply
function sessionMessages(s){
  if(s.messages&&s.messages.length)return s.messages;
  const out=[];
  for(const e of s.events){
    if(e.actor==='user'&&(e.family==='intent'||e.family==='feedback'))out.push({ts:e.ts-1,role:'user',len:30+Math.floor((e.ts*7)%140),text:null});
    else if(e.family==='delivery'&&/ANSWER_GIVEN|ARTIFACT_PRODUCED|NARRATED/.test(e.label))out.push({ts:e.ts,role:'iris',len:80+Math.floor((e.ts*13)%420),text:null})}
  if(!out.length)out.push({ts:s.started,role:'user',len:60,text:null});
  return out}
// The design language (MEMORY-DASHBOARD-DESIGN §18): FRAGMENT, STRAND, GLYPH, SYNC, DESYNC, ASSEMBLY. A session is relived
// the way the Animus replays a memory: the corridor ASSEMBLES out of wall fragments around you as you travel, the
// conversation and the memory run through it as one DOUBLE STRAND (conversations.db and memory.db, a rung wherever a
// moment belongs to a turn), moments and messages are shard fragments on their strand, claims are the glyph, and where
// the work failed the corridor DESYNCS. Organic only in motion: the fragments breathe, loosen where the session was quiet.
//
// strands: screen-space ribbons of light, a fixed width in pixels
const RIB_VS=`uniform float uTime,uSpeed,uLen;uniform vec2 uRes;uniform vec4 uHL[8];
  attribute vec3 aNx,aCol;attribute float aSide,aU,aB,aW;varying vec3 vC;varying float vA,vS;
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vec4 c0=projectionMatrix*mv,c1=projectionMatrix*modelViewMatrix*vec4(position+aNx,1.);
    vec2 p0=c0.xy/max(c0.w,1e-4)*uRes*.5,p1=c1.xy/max(c1.w,1e-4)*uRes*.5,d=p1-p0;float sl=length(d);d=sl>1e-4?d/sl:vec2(1.,0.);
    float fs=sl/max(length(aNx)*projectionMatrix[1][1]*uRes.y*.5/max(-mv.z,.1),1e-4);   // seen end-on, a strand would pile up its light: fade it
    float zf=-mv.z;c0.xy+=vec2(-d.y,d.x)*aW*mix(1.,.35,smoothstep(12.,60.,zf))*aSide/(uRes*.5)*c0.w;   // thinner far off, so far turns do not pile up
    float hl=0.;for(int j=0;j<8;j++){vec4 h=uHL[j];if(h.x>-.5&&abs(aB-h.x)<.5)hl+=h.w*smoothstep(h.y-.002,h.y+.002,aU)*(1.-smoothstep(h.z-.002,h.z+.002,aU));}
    float pulse=pow(.5+.5*sin(aU*uLen*.55-uTime*uSpeed+aB*2.1),18.)*step(aB,1.5);   // data runs along the two strands
    float z=-mv.z;vA=smoothstep(75.,6.,z)*smoothstep(.25,1.4,z)*smoothstep(.04,.3,fs)*smoothstep(1.5,10.,sl);vC=aCol*(1.+hl*1.1+pulse*.7);vS=aSide;gl_Position=c0;}`;
const RIB_FS=`varying vec3 vC;varying float vA,vS;void main(){float e=1.-vS*vS;gl_FragColor=vec4(vC,vA*e*.9);}`;
// fragments ON the strands (moments, messages): a camera-facing hex shard with three facets and a bright edge; a strong
// source is solid, a weak one only its edge (trust as solidity)
const SHARD_VS=`uniform float uPix,uTime;uniform vec4 uHL[8];attribute vec3 aCol;attribute float aSize,aU,aB,aSolid,aR;
  varying vec3 vC;varying float vA,vSolid,vRot;
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float z=-mv.z;
    float hl=0.;for(int j=0;j<8;j++){vec4 h=uHL[j];if(h.x>-.5&&abs(aB-h.x)<.5)hl+=h.w*smoothstep(h.y-.002,h.y+.002,aU)*(1.-smoothstep(h.z-.002,h.z+.002,aU));}
    vC=aCol*(1.+hl*.9);vSolid=aSolid;vRot=aR*6.2832+uTime*.15*(aR-.5);
    vA=smoothstep(120.,8.,z)*smoothstep(.25,1.6,z)*(.7+.3*min(hl,1.));
    gl_PointSize=min(aSize*(1.+hl*.35)*uPix*(42./max(z,.1)),48.*uPix);gl_Position=projectionMatrix*mv;}`;
const SHARD_FS=`varying vec3 vC;varying float vA,vSolid,vRot;
  void main(){vec2 p=gl_PointCoord*2.-1.;float c=cos(vRot),s=sin(vRot);p=mat2(c,-s,s,c)*p;vec2 q=abs(p);
    float hx=max(q.x*.866+q.y*.5,q.y);if(hx>.92)discard;
    float facet=mod(floor((atan(p.y,p.x)+3.1416)/2.0944),3.);float shade=.45+.2*facet;      // three facets catch the light differently
    float edge=smoothstep(.72,.9,hx);
    gl_FragColor=vec4(vC*(shade*vSolid*.7+edge*.95),(vSolid*.45+edge*.75)*vA);}`;
// the corridor's WALL: hex fragments laid on the wall. They assemble around you (scattered and dim further off), breathe,
// loosen where the session was quiet, tint where a task closed, and glitch (desync) where the work failed.
const TILE_VS=`uniform float uTime,uAsm,uLen;uniform vec4 uDes[8];attribute vec3 aCen,aNrm,aCol;attribute float aEdge,aU,aR,aAct;
  varying vec3 vC;varying float vA,vE,vG,vW;
  float h1(float x){return fract(sin(x*127.1)*43758.5453);}
  void main(){vec4 mc=modelViewMatrix*vec4(aCen,1.);float z=-mc.z;
    float asb=uAsm*(1.-smoothstep(30.,80.,z));                                   // assembled near you, scattered further off
    vec3 sc=normalize(vec3(h1(aR*13.1)-.5,h1(aR*7.7)-.5,h1(aR*3.3)-.5)+aNrm*.6)*(1.-asb)*(2.2+3.*aR);
    float br=(.02+.035*(1.-aAct))*sin(uTime*(1.05+aR*.35)+aR*40.);               // breathing (5-6 s), looser where it was quiet
    // shedding: where the session was quiet a few fragments come loose, drift into the corridor and fade
    float shed=step(aR,.06*(1.-aAct)),sp=fract(uTime*.045+aR*17.);
    vec3 p=aCen+(position-aCen)*mix(.62,.9,aAct)*mix(.4,1.,asb)*(1.-shed*sp*.5)+aNrm*(br-shed*sp*1.4)+sc;
    float g=0.;for(int j=0;j<8;j++){vec4 d=uDes[j];if(d.w<=0.)continue;float q=(aU-d.x)/.01,w=exp(-q*q);
      float on=step(.82,h1(floor(uTime*5.)+d.x*91.));                               // the desync comes and goes (a glitch, not a state)
      g+=w*on*d.w;}
    p+=(vec3(h1(floor(uTime*12.)+aR*31.),h1(floor(uTime*12.)+aR*17.),h1(floor(uTime*12.)+aR*5.))-.5)*g*.3;
    vec4 mv=modelViewMatrix*vec4(p,1.);vC=aCol*(.55+.45*h1(aR*91.));vE=aEdge;vG=min(g,1.);
    vW=pow(.5+.5*sin(aU*uLen*.22-uTime*.9),24.)*(.4+.6*aAct);                 // a slow wave of light runs down the wall
    vA=smoothstep(85.,12.,-mv.z)*smoothstep(1.2,4.5,-mv.z)*(.35+.65*asb)*(.4+.6*aAct)*(1.-shed*smoothstep(.5,1.,sp));gl_Position=projectionMatrix*mv;}`;
const TILE_FS=`varying vec3 vC;varying float vA,vE,vG,vW;
  void main(){float edge=smoothstep(.86,.98,vE);vec3 c=vC*(.1+edge*.6)*(1.+vW*1.4);
    c=mix(c,vec3(1.,.25,.32)*(.3+edge*.7),vG*.65);c.b+=vG*edge*.3;               // desync: a red shift and a chromatic edge
    gl_FragColor=vec4(c,(.03+edge*.2)*vA);}`;

// the doorway: a tall arch with a soft edge (no rim line, nothing round); the fibres of the tunnel part round it and frame it.
// Coordinates are in units of the tunnel radius at the door: half-width .55, sill -1.15, springing .35, crown .9
const ARCH_SDF=`float archSdf(vec2 p){return p.y>.35?length(vec2(p.x,p.y-.35))-.55:max(abs(p.x)-.55,-1.15-p.y);}`;
const archSdfJS=(x,y)=>y>.35?Math.hypot(x,y-.35)-.55:Math.max(Math.abs(x)-.55,-1.15-y);
function archRay(al){const dx=Math.cos(al),dy=Math.sin(al);let lo=0,hi=6;for(let i=0;i<26;i++){const m=(lo+hi)/2;archSdfJS(dx*m,dy*m)<0?lo=m:hi=m}return [dx*lo,dy*lo]}
const archGeo=new THREE.PlaneGeometry(1.5,2.5).translate(0,-.125,0);
const doorMat=(a,b,dir)=>new THREE.ShaderMaterial({uniforms:{...U,uOpen:{value:0},uA:{value:a},uB:{value:b},uDir:{value:dir}},
  vertexShader:`varying vec2 vXY;void main(){vXY=position.xy;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
  fragmentShader:`uniform float uTime,uOpen,uDir;uniform vec3 uA,uB;varying vec2 vXY;${ARCH_SDF}
    void main(){vec2 p=vXY;float open=mix(.28,1.,uOpen);
      float sd=archSdf(p/open)*open;float inside=1.-smoothstep(-.7,0.,sd);inside*=inside;   // soft edge: it fades over the outer half, no line
      vec2 q=p-vec2(0.,-.1);float r=length(q),a=atan(q.y,q.x);
      float sp=sin(a*7.+uDir*log(max(r,.02))*9.-uTime*2.2*uDir);              // the swirl beyond
      vec3 beyond=mix(uB*.05,uB*.3,smoothstep(.55,1.,sp))*(1.-clamp(r,0.,1.3)*.4);
      gl_FragColor=vec4(beyond*inside+uA*.05*inside,inside*.72);}`,
  transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide});
function buildTunnel(s){
  rng=mulberry32(s.id.split('').reduce((a,c)=>a*31+c.charCodeAt(0)|0,7));
  const g=new THREE.Group();g.position.copy(TUN_OFF);
  const ev=s.events;const L=90+Math.min(ev.length,260)*1.5;
  const ctrl=[];for(let k=0;k<=12;k++)ctrl.push(new V3(Math.sin(k*.9)*2.2+gauss()*.4,Math.cos(k*.7)*1.4+gauss()*.3,-k*L/12));
  const curve=new THREE.CatmullRomCurve3(ctrl);const FR=curve.computeFrenetFrames(600,false);const CL=curve.getLength();
  const tSpan=Math.max(1,(s.ended||nowS())-s.started);
  const uOf=ts=>clamp(.04+.9*(ts-s.started)/tSpan,.02,.96);
  const eps=s.episodes.map(id=>M.epById.get(id)).filter(Boolean);const epS=eps.map(e=>uOf(e.ts));
  const tr=s.traj.length?s.traj:[{x:0}];
  const trX=k=>clamp(.5+.5*(tr[Math.min(tr.length-1,Math.max(0,k))].x||0),0,1);
  const radius=u=>{const f=clamp(u,0,.999)*tr.length-.5,k=Math.floor(f),t=smooth01(f-k);let r=3.6*(.66+.6*lerp(trX(k),trX(k+1),t));
    for(const q of epS)r*=1+.2*Math.exp(-Math.pow((u-q)/.03,2));return r};
  const frameAt=u=>{const i=Math.min(599,Math.floor(clamp(u,0,1)*600));return {N:FR.normals[i],B:FR.binormals[i],T:FR.tangents[i]}};
  const onWall=(u,th,k=1)=>{u=clamp(u,0,1);const P=curve.getPointAt(u),{N,B}=frameAt(u);const r=radius(u)*k;
    return P.addScaledVector(N,Math.cos(th)*r).addScaledVector(B,Math.sin(th)*r)};
  const TW=6.283*2.4; // the double strand's axis turns 2.4 times round the corridor through the session
  const msgs=sessionMessages(s);
  // ── the door frame (the corridor's end): up = world up made square to the tunnel, the arch stands in that plane
  const P1=curve.getPointAt(1),T1=frameAt(1).T.clone(),rad1=radius(1);
  const Ud=new V3(0,1,0).addScaledVector(T1,-T1.y);if(Ud.lengthSq()<1e-4)Ud.set(1,0,0);Ud.normalize();
  const Rd=new V3().crossVectors(T1,Ud).normalize();

  // ── the DOUBLE STRAND: a centre line spiralling just inside the wall; strand A (the conversation) and strand B (the
  // memory) twist round it. A fan-out opens the pair into a replication fork that closes again; a forked conversation
  // leaves as its own thinner double strand.
  const splits=ev.filter(e=>e.label==='SPLIT').map(e=>{const u0=uOf(e.ts);return {u0,u1:Math.min(.96,u0+rand(.04,.07))}});
  const fork=u=>{let a=0;for(const f of splits)a=Math.max(a,smooth01((u-f.u0)/.012)*(1-smooth01((u-f.u1+.012)/.012)));return a};
  const pairs=[{kind:'thread',th0:0,u0:0,u1:1,k:.48,rho:1.2,w:[1.7,1.5],col:[new THREE.Color('#f2c9ec'),new THREE.Color('#9fdcf0')]}];
  (s.strands||[]).forEach((cs,j)=>pairs.push({kind:'strand',id:cs.id,label:cs.title||'a strand of this conversation',th0:Math.PI*(.9+.25*j),
    u0:uOf(cs.started),u1:cs.ended?uOf(cs.ended):1,k:.72,rho:.55,w:[1.1,1],col:[new THREE.Color('#e3a8db'),new THREE.Color('#7fc6dc')]}));
  const centre=(pr,u)=>{let th=pr.th0+u*TW;if(pr.kind==='strand'){const w=smooth01((u-pr.u0)/.05)*(pr.u1>=.99?1:smooth01((pr.u1-u)/.05));th=lerp(u*TW,th,w)}
    return onWall(u,th,pr.k)};
  const SAMP=.3,paths=[];   // samples every SAMP world units
  pairs.forEach((pr,pi)=>{const len=(pr.u1-pr.u0)*CL*1.1,n=Math.max(12,Math.round(len/SAMP)),C=[],us=[];
    for(let k=0;k<n;k++){const u=pr.u0+(pr.u1-pr.u0)*k/(n-1);us.push(u);C.push(centre(pr,u))}
    // parallel-transported frame along the centre line, so the twist has no jumps
    const Ns=[],Bs=[];let Nr=null;
    for(let k=0;k<n;k++){const T=C[Math.min(k+1,n-1)].clone().sub(C[Math.max(k-1,0)]).normalize();
      if(!Nr){Nr=Math.abs(T.y)<.9?new V3(0,1,0):new V3(1,0,0);Nr.addScaledVector(T,-Nr.dot(T)).normalize()}
      else{Nr=Nr.clone().addScaledVector(T,-Nr.dot(T));if(Nr.lengthSq()<1e-8)Nr.set(T.y,-T.x,0);Nr.normalize()}Ns.push(Nr);Bs.push(new V3().crossVectors(T,Nr))}
    const A=[],B=[];let sl=0;const arch=pr.u1>=.99;
    let tgA=null,tgB=null,extA=[],extB=[];if(arch){const e=C[n-1].clone().sub(P1),al=Math.atan2(e.dot(Ud),e.dot(Rd));
      const onArch=a=>{const [x,y]=archRay(a);return P1.clone().addScaledVector(Rd,x*rad1).addScaledVector(Ud,y*rad1)};
      tgA=onArch(al-.06);tgB=onArch(al+.06);
      // past the climb the pair parts and each strand traces the arch one way round: the doorway is framed by the session
      for(let i=1;i<=40;i++){const f=i/40*Math.PI*.95;extA.push(onArch(al-.06-f));extB.push(onArch(al+.06+f))}}
    for(let k=0;k<n;k++){if(k)sl+=C[k].distanceTo(C[k-1]);const ph=sl*.42+pi,r=pr.rho*radius(us[k])/3.6*(1+.45*fork(us[k]))*(pr.kind==='thread'?1:.9);   // a wide, slow coil: one turn every ~15 units
      const o=Ns[k].clone().multiplyScalar(Math.cos(ph)*r).addScaledVector(Bs[k],Math.sin(ph)*r);
      let a=C[k].clone().add(o),b=C[k].clone().sub(o);
      if(arch){const t=smooth01((us[k]-.93)/.07);if(t>0){a.lerp(tgA,t*t);b.lerp(tgB,t*t)}}   // the pair climbs onto the arch
      A.push(a);B.push(b)}
    paths.push({pr,us,A,B,n,extA,extB})});
  const at=(path,which,u)=>{const P=which?path.B:path.A,k=clamp(Math.round((u-path.pr.u0)/(path.pr.u1-path.pr.u0)*(path.n-1)),0,path.n-1);return P[k]};

  // ── ribbons: the strands, their rungs, and the short stem from a moment to its claim
  const RB={pos:[],nx:[],side:[],u:[],b:[],col:[],w:[],idx:[]};
  const ribbon=(Ps,us,bi,col,wpx,mul=null)=>{const n=Ps.length;if(n<2)return;const base=RB.pos.length/3;
    for(let k=0;k<n;k++){const a=Ps[Math.max(0,k-1)],c=Ps[Math.min(n-1,k+1)],m=mul?mul[k]:1;
      for(const sd of [-1,1]){RB.pos.push(Ps[k].x,Ps[k].y,Ps[k].z);RB.nx.push(c.x-a.x,c.y-a.y,c.z-a.z);RB.side.push(sd);RB.u.push(us[k]);RB.b.push(bi);
        RB.col.push(col.r*m,col.g*m,col.b*m);RB.w.push(wpx)}}
    for(let k=0;k<n-1;k++){const i=base+2*k;RB.idx.push(i,i+1,i+2,i+1,i+3,i+2)}};
  // light a run of a strand where a message or a moment sits (the strand brightens there, never glares)
  const lit=paths.map(p=>[new Float32Array(p.n).fill(.42),new Float32Array(p.n).fill(.42)]);
  const lightAt=(pi,which,u,amt)=>{const p=paths[pi],k0=(u-p.pr.u0)/(p.pr.u1-p.pr.u0)*(p.n-1);
    for(let k=Math.max(0,Math.floor(k0-3));k<=Math.min(p.n-1,Math.ceil(k0+3));k++)lit[pi][which][k]=Math.max(lit[pi][which][k],.42+amt*Math.exp(-Math.pow((k-k0)/1.6,2)))};

  // ── items: a message is a fragment on strand A, a moment a fragment on strand B, tied to its turn by a rung
  const items=[],SH={pos:[],col:[],size:[],u:[],b:[],solid:[],r:[]};
  const shard=(P,c,size,u,b,solid)=>{SH.pos.push(P.x,P.y,P.z);SH.col.push(c.r,c.g,c.b);SH.size.push(size);SH.u.push(u);SH.b.push(b);SH.solid.push(solid);SH.r.push(rng())};
  const P0=paths[0];
  msgs.forEach(m=>{const u=uOf(m.ts),span=Math.min(.03,(1+Math.min(6,Math.round((m.len||60)/90)))*.004),P=at(P0,0,u);
    const user=m.role==='user',c=new THREE.Color(user?'#fbe9f7':'#f08ad6');
    shard(P,c,user?2.6:2.1,u,0,user?1:.8);lightAt(0,0,u,.9);
    items.push({type:'msg',m,u,bundle:0,ua:u,ub:Math.min(.99,u+span),world:P.clone().add(TUN_OFF),links:[]})});
  const msgItems=items.slice();
  ev.forEach(e=>{const u=uOf(e.ts),P=at(P0,1,u);
    const c=(e.valence==='sets_back'?new THREE.Color('#ff5a4d'):new THREE.Color(FAM[FAMI[e.family]??0].color)).multiplyScalar(.75+(e.actor==='user'?.25:0));
    const strong=(EVID[e.evidence]??.2)>=.5;shard(P,c,1.5+1.2*(EVID[e.evidence]??.2),u,1,strong?1:.15);lightAt(0,1,u,.7);
    let mi=null;for(const it of msgItems){if(it.m.ts<=e.ts+1)mi=it;else break}
    const item={type:'event',e,u,bundle:1,ua:u,ub:Math.min(.99,u+.004),col:c,world:P.clone().add(TUN_OFF),links:mi?[mi]:[]};items.push(item);if(mi)mi.links.push(item)});
  // the strands themselves
  paths.forEach((p,pi)=>{const pr=p.pr,fade=p.extA.map((_,i)=>.42*(1-i/p.extA.length)),u1=p.extA.map(()=>1);
    ribbon(p.A.concat(p.extA),p.us.concat(u1),pi===0?0:2,pr.col[0],pr.w[0],[...lit[pi][0],...fade]);
    ribbon(p.B.concat(p.extB),p.us.concat(u1),pi===0?1:3,pr.col[1],pr.w[1],[...lit[pi][1],...fade])});
  // rungs: a faint one every so often (the structure), a coloured one wherever a moment belongs to a turn (the meaning)
  paths.forEach((p,pi)=>{const step=Math.max(1,Math.round(1.5/SAMP));
    // the coil is wide, so a plain rung is only a short stub off each strand toward the other (never a line across the corridor)
    const rc=new THREE.Color('#9fb6c8');
    for(let k=0;k<p.n;k+=step){const a=p.A[k],b=p.B[k],u=p.us[k];ribbon([a,a.clone().lerp(b,.16)],[u,u],9,rc,.7,[.24,0]);ribbon([b,b.clone().lerp(a,.16)],[u,u],9,rc,.7,[.24,0])}});
  // a moment's rung to its turn: a stub off each strand toward the other - a bond, never a bar across the corridor
  items.forEach(it=>{if(it.type!=='event'||!it.links[0])return;const a=at(P0,0,it.u),b=at(P0,1,it.u),m=[];for(let i=0;i<=8;i++)m.push(a.clone().lerp(b,i/8));
    ribbon(m,m.map(()=>it.u),1,it.col,1.1,m.map((_,i)=>.5*Math.max(0,1-Math.min(i,8-i)/2.6)))});   // two stubs reaching for each other, open between
  // claims: the SAME glyph as in the cortex, just off the memory strand where the moment touched it, on a short stem
  const stars=[];
  items.forEach(it=>{if(it.type!=='event'||it.e.landmark==null||it.e.landmark>=NL||stars.length>=60)return;
    const B_=at(P0,1,it.u),C_=curve.getPointAt(clamp(it.u,0,1)),out=B_.clone().sub(C_).normalize(),p=B_.clone().addScaledVector(out,.55);
    ribbon([B_,p],[it.u,it.u],1,new THREE.Color(CELL_COL[lmBest[it.e.landmark]]||'#8aa3b0'),.9,[.6,.6]);
    stars.push({li:it.e.landmark,u:it.u,th:0,p,world:p.clone().add(TUN_OFF),item:it})});

  // ── the WALL: hex fragments, assembled around you. Activity = how busy the session was there (its moments).
  const ACT=new Float32Array(120);ev.forEach(e=>{ACT[Math.min(119,Math.floor(uOf(e.ts)*120))]++});
  {const mx=Math.max(1,...ACT);for(let i=0;i<120;i++)ACT[i]=Math.pow(ACT[i]/mx,.5)}
  const actAt=u=>{let a=0;for(let d=-2;d<=2;d++){const i=Math.min(119,Math.max(0,Math.floor(u*120)+d));a=Math.max(a,ACT[i]*(1-Math.abs(d)*.2))}return clamp(.25+a*.75,0,1)};
  const gates=[],gateCol=eps.map(ep=>new THREE.Color(ep.corrected?'#ffffff':ep.outcome==='failure'?'#ff4a3d':ep.outcome==='partial'?'#ffb547':ep.outcome==='running'?THEMES[themeIdx][1]:'#7fe8ff'));
  eps.forEach((ep,qi)=>gates.push({ep,u:epS[qi],world:curve.getPointAt(epS[qi]).add(TUN_OFF)}));
  const WT={pos:[],cen:[],nrm:[],col:[],edge:[],u:[],r:[],act:[],idx:[]};
  // Fragments are small and many, and they cluster: a slow field over the wall (two crossing waves) sets where they sit
  // close and full-sized and where they thin out, so the wall reads as a growth, not a grid. Budget: ~22k fragments.
  {const SP=Math.max(.42,Math.sqrt((CL*2*Math.PI*4.2)/22000)),rings=Math.max(30,Math.round(CL/(SP*.87))),base=new THREE.Color('#b8d4e2'),tmp=new THREE.Color();
    const f1=rng()*6.28,f2=rng()*6.28,field=(u,th)=>.5+.5*Math.sin(u*CL*.19+th*3+f1)*Math.sin(u*CL*.11-th*2+f2);
    for(let r=0;r<rings;r++){const u0=clamp((r+.5)/rings,0,1),rr0=radius(u0)*1.05,per=Math.max(16,Math.round(2*Math.PI*rr0/SP)),act=actAt(u0);
      for(let q=0;q<per;q++){const th=(q+(r%2)*.5+(rng()-.5)*.3)/per*6.2832,u=clamp(u0+(rng()-.5)*.3/rings,0,1),fd=field(u,th);
        if(rng()>(.3+.7*act)*(.4+.6*fd))continue;                                 // quiet or thin stretches have gaps
        const {N,B,T}=frameAt(u),nrm=N.clone().multiplyScalar(Math.cos(th)).addScaledVector(B,Math.sin(th)),rr=radius(u)*1.05*(1+.015*(rng()-.5));
        let gc=null;for(let k=0;k<epS.length;k++)if(Math.abs(u-epS[k])<.0025)gc=gateCol[k];   // a task's close: a thin tinted ring
        const cen=curve.getPointAt(u).addScaledVector(nrm,rr),tan=new V3().crossVectors(nrm,T).normalize(),hr=SP*.5*(.5+.5*fd)*rand(.85,1.05),rot=(rng()-.5)*.5,rr_=rng(),bi=WT.pos.length/3;
        tmp.copy(base).multiplyScalar(.7+.3*act);if(gc)tmp.lerp(gc,.55);
        const push=(P,e)=>{WT.pos.push(P.x,P.y,P.z);WT.cen.push(cen.x,cen.y,cen.z);WT.nrm.push(nrm.x,nrm.y,nrm.z);WT.col.push(tmp.r,tmp.g,tmp.b);WT.edge.push(e);WT.u.push(u);WT.r.push(rr_);WT.act.push(act)};
        push(cen,0);for(let k=0;k<6;k++){const a=k/6*6.2832+.5236+rot;push(cen.clone().addScaledVector(tan,Math.cos(a)*hr).addScaledVector(T,Math.sin(a)*hr),1)}
        for(let k=0;k<6;k++)WT.idx.push(bi,bi+1+k,bi+1+(k+1)%6)}}}
  const desync=[];eps.forEach((ep,qi)=>{if(ep.outcome==='failure'&&desync.length<8)desync.push(new THREE.Vector4(epS[qi],0,0,1))});
  ev.forEach(e=>{if(e.valence==='sets_back'&&desync.length<8)desync.push(new THREE.Vector4(uOf(e.ts),0,0,.35))});
  while(desync.length<8)desync.push(new THREE.Vector4(0,0,0,0));
  const tileU={...U,uAsm:{value:0},uDes:{value:desync},uLen:{value:L}};
  {const tg=new THREE.BufferGeometry();tg.setAttribute('position',new THREE.Float32BufferAttribute(WT.pos,3));tg.setAttribute('aCen',new THREE.Float32BufferAttribute(WT.cen,3));
    tg.setAttribute('aNrm',new THREE.Float32BufferAttribute(WT.nrm,3));tg.setAttribute('aCol',new THREE.Float32BufferAttribute(WT.col,3));tg.setAttribute('aEdge',new THREE.Float32BufferAttribute(WT.edge,1));
    tg.setAttribute('aU',new THREE.Float32BufferAttribute(WT.u,1));tg.setAttribute('aR',new THREE.Float32BufferAttribute(WT.r,1));tg.setAttribute('aAct',new THREE.Float32BufferAttribute(WT.act,1));
    tg.setIndex(WT.pos.length/3>65535?new THREE.Uint32BufferAttribute(WT.idx,1):new THREE.Uint16BufferAttribute(WT.idx,1));
    g.add(Object.assign(new THREE.Mesh(tg,new THREE.ShaderMaterial({uniforms:tileU,vertexShader:TILE_VS,fragmentShader:TILE_FS,transparent:true,depthWrite:false,
      blending:THREE.AdditiveBlending,side:THREE.DoubleSide})),{frustumCulled:false}))}

  // ── strands mesh + shard fragments
  const meanU=tr.reduce((a,p)=>a+Math.abs(p.u??.5),0)/tr.length;
  const hlU={value:Array.from({length:8},()=>new THREE.Vector4(-1,0,0,0))};
  const fibU={...U,uSpeed:{value:1.4+2.4*meanU},uLen:{value:L},uHL:hlU,uRes:{value:new THREE.Vector2(innerWidth,innerHeight)}};
  {const rg=new THREE.BufferGeometry();rg.setAttribute('position',new THREE.Float32BufferAttribute(RB.pos,3));rg.setAttribute('aNx',new THREE.Float32BufferAttribute(RB.nx,3));
    rg.setAttribute('aSide',new THREE.Float32BufferAttribute(RB.side,1));rg.setAttribute('aU',new THREE.Float32BufferAttribute(RB.u,1));rg.setAttribute('aB',new THREE.Float32BufferAttribute(RB.b,1));
    rg.setAttribute('aCol',new THREE.Float32BufferAttribute(RB.col,3));rg.setAttribute('aW',new THREE.Float32BufferAttribute(RB.w,1));
    rg.setIndex(RB.pos.length/3>65535?new THREE.Uint32BufferAttribute(RB.idx,1):new THREE.Uint16BufferAttribute(RB.idx,1));
    g.add(Object.assign(new THREE.Mesh(rg,new THREE.ShaderMaterial({uniforms:fibU,vertexShader:RIB_VS,fragmentShader:RIB_FS,transparent:true,depthWrite:false,
      blending:THREE.AdditiveBlending,side:THREE.DoubleSide})),{frustumCulled:false}))}
  {const sg=new THREE.BufferGeometry();sg.setAttribute('position',new THREE.Float32BufferAttribute(SH.pos,3));sg.setAttribute('aCol',new THREE.Float32BufferAttribute(SH.col,3));
    sg.setAttribute('aSize',new THREE.Float32BufferAttribute(SH.size,1));sg.setAttribute('aU',new THREE.Float32BufferAttribute(SH.u,1));sg.setAttribute('aB',new THREE.Float32BufferAttribute(SH.b,1));
    sg.setAttribute('aSolid',new THREE.Float32BufferAttribute(SH.solid,1));sg.setAttribute('aR',new THREE.Float32BufferAttribute(SH.r,1));
    g.add(Object.assign(new THREE.Points(sg,new THREE.ShaderMaterial({uniforms:{...U,uHL:hlU},vertexShader:SHARD_VS,fragmentShader:SHARD_FS,transparent:true,depthWrite:false,
      blending:THREE.AdditiveBlending})),{frustumCulled:false,renderOrder:3}))}

  // ── the wall in depth (owner, 2026-10-19: "more detail on the walls so it does not look as empty"). Three layers, each
  // carrying something real: behind the fragments the wall's own fine LATTICE (the cortex's triangle geometry, slowly
  // warped, thinner where the session was quiet); DATA STREAMS - short dashes of light that run down the wall toward the
  // doorway, densest where the session was busy and tinted by the kind of moment that happened there; and INSCRIPTIONS -
  // the name of a moment written faintly where it happened, typing itself in as you approach.
  const famBin=new Array(120).fill(null);{const cnt=Array.from({length:120},()=>new Map());
    ev.forEach(e=>{const b=Math.min(119,Math.floor(uOf(e.ts)*120)),f=FAMI[e.family]??0;cnt[b].set(f,(cnt[b].get(f)||0)+1)});
    cnt.forEach((m,b)=>{let best=null,n=0;m.forEach((v,k)=>{if(v>n){n=v;best=k}});famBin[b]=best})}
  const pale=new THREE.Color('#9fc4d8');
  {const SP2=Math.max(.9,Math.sqrt((CL*2*Math.PI*4.4)/9000)),rings=Math.max(20,Math.round(CL/(SP2*.87))),per=Math.max(16,Math.round(2*Math.PI*3.6*1.18/SP2));
    const rowsP=[];for(let r=0;r<=rings;r++){const u=r/rings,row=[],{N,B}=frameAt(u),Cc=curve.getPointAt(u),rr=radius(u)*1.18;
      for(let q=0;q<per;q++){const th=(q+(r%2)*.5)/per*6.2832+.12*Math.sin(u*CL*.05+q*.7),k=1+.035*Math.sin(u*CL*.13+th*3);
        row.push(Cc.clone().addScaledVector(N,Math.cos(th)*rr*k).addScaledVector(B,Math.sin(th)*rr*k))}rowsP.push({u,row})}
    const LP=[],LU=[],LR=[];const seg=(a,b,u)=>{LP.push(a.x,a.y,a.z,b.x,b.y,b.z);LU.push(u,u);const r_=rng();LR.push(r_,r_)};
    for(let r=0;r<rings;r++){const A_=rowsP[r],B_=rowsP[r+1],act=actAt(A_.u);
      for(let q=0;q<per;q++){if(rng()>.3+.7*act)continue;const q2=r%2?(q+1)%per:q;
        seg(A_.row[q],A_.row[(q+1)%per],A_.u);seg(A_.row[q],B_.row[q2],A_.u);seg(A_.row[q],B_.row[(q2-1+per)%per],A_.u)}}
    const lg=new THREE.BufferGeometry();lg.setAttribute('position',new THREE.Float32BufferAttribute(LP,3));lg.setAttribute('aU',new THREE.Float32BufferAttribute(LU,1));lg.setAttribute('aR',new THREE.Float32BufferAttribute(LR,1));
    g.add(Object.assign(new THREE.LineSegments(lg,new THREE.ShaderMaterial({uniforms:{...U,uLen:{value:L},uC:{value:pale}},
      vertexShader:`uniform float uTime,uLen;attribute float aU,aR;varying float vA;
        void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float z=-mv.z;float w=pow(.5+.5*sin(aU*uLen*.22-uTime*.9),24.);
          vA=smoothstep(70.,8.,z)*smoothstep(3.,9.,z)*(.045+.03*sin(uTime*(.6+aR*.4)+aR*30.)+w*.1);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`uniform vec3 uC;varying float vA;void main(){gl_FragColor=vec4(uC,vA);}`,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false}))}
  {const NSt=Math.round(clamp(CL*10,1200,4500)),SA=[],SB=[],SPh=[],SSp=[],SL=[],SC=[],Z=[];
    for(let i=0;i<NSt;i++){let u=rng();if(rng()>.25+.75*actAt(u))u=rng();
      const th=rng()*6.2832,len=rand(3,9)/CL,a=onWall(u,th,1.1),b=onWall(Math.min(1,u+len),th+rand(-.04,.04),1.1);
      const fb=famBin[Math.min(119,Math.floor(u*120))],c=fb!=null&&rng()<.55?new THREE.Color(FAM[fb].color).lerp(pale,.5):pale.clone();
      const ph=rng(),sp=rand(.1,.3)*(.6+meanU);
      for(const lag of [0,1]){Z.push(0,0,0);SA.push(a.x,a.y,a.z);SB.push(b.x,b.y,b.z);SPh.push(ph);SSp.push(sp);SL.push(lag);SC.push(c.r,c.g,c.b)}}
    const sg=new THREE.BufferGeometry();sg.setAttribute('position',new THREE.Float32BufferAttribute(Z,3));sg.setAttribute('aA',new THREE.Float32BufferAttribute(SA,3));
    sg.setAttribute('aB',new THREE.Float32BufferAttribute(SB,3));sg.setAttribute('aPh',new THREE.Float32BufferAttribute(SPh,1));sg.setAttribute('aSp',new THREE.Float32BufferAttribute(SSp,1));
    sg.setAttribute('aLag',new THREE.Float32BufferAttribute(SL,1));sg.setAttribute('aC',new THREE.Float32BufferAttribute(SC,3));
    g.add(Object.assign(new THREE.LineSegments(sg,new THREE.ShaderMaterial({uniforms:{...U},
      vertexShader:`uniform float uTime;attribute vec3 aA,aB,aC;attribute float aPh,aSp,aLag;varying vec3 vC;varying float vA;
        void main(){float f=fract(aPh+uTime*aSp),t=clamp(f-aLag*.14,0.,1.);vec4 mv=modelViewMatrix*vec4(mix(aA,aB,t),1.);float z=-mv.z;
          vC=aC;vA=sin(3.1416*f)*(1.-aLag)*smoothstep(60.,6.,z)*smoothstep(1.,4.,z)*.42;gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`varying vec3 vC;varying float vA;void main(){gl_FragColor=vec4(vC,vA);}`,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false}))}
  {const wordOf=e=>String(e.label||'').toLowerCase().replace(/_/g,' ');const list=ev.filter(e=>e.label);
    const nPick=Math.min(140,list.length),chosen=[];for(let i=0;i<nPick;i++)chosen.push(list[Math.floor(i*list.length/nPick)]);
    const words=[],wi=new Map();chosen.forEach(e=>{const w=wordOf(e);if(!wi.has(w)&&words.length<48){wi.set(w,words.length);words.push(w)}});
    if(words.length){const RH=40,cvs=document.createElement('canvas');cvs.width=1024;cvs.height=RH*48;const cx=cvs.getContext('2d');
      cx.font="500 26px 'JetBrains Mono',ui-monospace,monospace";cx.fillStyle='#fff';cx.textBaseline='middle';
      const wid=words.map((w,i)=>{cx.fillText(w,6,i*RH+RH/2);return Math.min(1,(cx.measureText(w).width+12)/1024)});
      const tex=new THREE.CanvasTexture(cvs);tex.anisotropy=4;
      const QP=[],QUV=[],QC=[],QX=[],QI=[];
      chosen.forEach(e=>{const k=wi.get(wordOf(e));if(k==null)return;const u=uOf(e.ts),P=onWall(u,rng()*6.2832,.9+.08*rng()),T=frameAt(u).T;
        const up=new V3(0,1,0).addScaledVector(T,-T.y);if(up.lengthSq()<1e-4)up.set(1,0,0);up.normalize();const rt=new V3().crossVectors(T,up).normalize();
        const h=.15,wd=h*wid[k]*1024/RH,c=new THREE.Color(FAM[FAMI[e.family]??0].color).lerp(pale,.55).multiplyScalar(.6+.5*(EVID[e.evidence]??.2)),base=QP.length/3;
        for(const [x,y] of [[0,-1],[1,-1],[1,1],[0,1]]){const p=P.clone().addScaledVector(rt,(x-.5)*wd).addScaledVector(up,y*h*.5);QP.push(p.x,p.y,p.z);
          QUV.push(x*wid[k],1-(k+(y<0?1:0))/48);QC.push(c.r,c.g,c.b);QX.push(x)}
        QI.push(base,base+1,base+2,base,base+2,base+3)});
      const qg=new THREE.BufferGeometry();qg.setAttribute('position',new THREE.Float32BufferAttribute(QP,3));qg.setAttribute('uv',new THREE.Float32BufferAttribute(QUV,2));
      qg.setAttribute('aC',new THREE.Float32BufferAttribute(QC,3));qg.setAttribute('aX',new THREE.Float32BufferAttribute(QX,1));qg.setIndex(QI);
      g.add(Object.assign(new THREE.Mesh(qg,new THREE.ShaderMaterial({uniforms:{...U,uMap:{value:tex}},
        vertexShader:`attribute vec3 aC;attribute float aX;varying vec2 vUv;varying vec3 vC;varying float vA,vX,vRev;
          void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float z=-mv.z;vUv=uv;vC=aC;vX=aX;
            vA=smoothstep(34.,12.,z)*smoothstep(1.,3.,z);vRev=smoothstep(30.,14.,z);gl_Position=projectionMatrix*mv;}`,
        fragmentShader:`uniform sampler2D uMap;varying vec2 vUv;varying vec3 vC;varying float vA,vX,vRev;
          void main(){if(vX>vRev+.02)discard;float a=texture2D(uMap,vUv).a,cur=(1.-smoothstep(0.,.03,abs(vX-vRev)))*step(vRev,.98);  // it types itself in
            gl_FragColor=vec4(vC*(1.+cur*2.),(a*.5+cur*.25)*vA);}`,
        transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide})),{frustumCulled:false}))}}
  // ── particles: data that travels the strands (hopping, the digital step), motes drifting toward the doorway (they
  // streak while you move), and a few very faint specks by the eye. Fixed budgets, low light.
  const partU={...U,uVel:{value:0}};
  {const BN=96,rows=[],tex=new Float32Array(BN*paths.length*2*4);
    paths.forEach(p=>[p.A,p.B].forEach(P=>rows.push(P)));
    rows.forEach((P,r)=>{const cum=[0];for(let k=1;k<P.length;k++)cum.push(cum[k-1]+P[k].distanceTo(P[k-1]));const tot=cum[cum.length-1]||1;let k=0;
      for(let i=0;i<BN;i++){const sv=i/(BN-1)*tot;while(k<P.length-2&&cum[k+1]<sv)k++;const f=clamp((sv-cum[k])/Math.max(1e-6,cum[k+1]-cum[k]),0,1);
        const q=P[k].clone().lerp(P[k+1],f);tex.set([q.x,q.y,q.z,1],(r*BN+i)*4)}});
    const pathTex=new THREE.DataTexture(tex,BN,rows.length,THREE.RGBAFormat,THREE.FloatType);pathTex.needsUpdate=true;
    const bp=[],brow=[],bph=[],bsp=[],bc=[],bnod=[];
    rows.forEach((P,r)=>{const n=r<2?8:4,c=r%2?new THREE.Color('#c9f1ff'):new THREE.Color('#ffe2f7');
      for(let i=0;i<n;i++){bp.push(0,0,0);brow.push(r);bph.push(rng());bsp.push((.006+.016*meanU)*rand(.7,1.3));bc.push(c.r,c.g,c.b);bnod.push(Math.max(6,Math.round(CL/2.2)))}});
    const bg=new THREE.BufferGeometry();bg.setAttribute('position',new THREE.Float32BufferAttribute(bp,3));bg.setAttribute('aRow',new THREE.Float32BufferAttribute(brow,1));
    bg.setAttribute('aPh',new THREE.Float32BufferAttribute(bph,1));bg.setAttribute('aSp',new THREE.Float32BufferAttribute(bsp,1));bg.setAttribute('aC',new THREE.Float32BufferAttribute(bc,3));
    bg.setAttribute('aNod',new THREE.Float32BufferAttribute(bnod,1));
    g.add(Object.assign(new THREE.Points(bg,new THREE.ShaderMaterial({uniforms:{...U,uPath:{value:pathTex},uN:{value:BN}},
      vertexShader:`uniform sampler2D uPath;uniform float uTime,uPix,uN;attribute float aRow,aPh,aSp,aNod;attribute vec3 aC;varying vec3 vC;varying float vA;
        void main(){float s=fract(aPh+uTime*aSp)*aNod,hop=smoothstep(.72,1.,fract(s));float t=(floor(s)+hop)/aNod*(uN-1.);
          int i=int(floor(t));float f=t-float(i);vec3 a=texelFetch(uPath,ivec2(i,int(aRow)),0).xyz,b=texelFetch(uPath,ivec2(min(i+1,int(uN)-1),int(aRow)),0).xyz;
          vec4 mv=modelViewMatrix*vec4(mix(a,b,f),1.);float d=-mv.z;vC=aC;vA=smoothstep(110.,10.,d)*smoothstep(.3,2.,d)*.55;
          gl_PointSize=min(2.4*uPix*(16./max(d,.1)),9.*uPix);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`varying vec3 vC;varying float vA;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
        float core=exp(-d*d*60.),halo=exp(-d*d*12.);gl_FragColor=vec4(vC*(core*.9+halo*.3),(core+halo*.45)*vA);}`,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false}))}
  {const pp=[],pt=[],pph=[],psp=[],pc=[],pk=[];
    const add=(P,Tv,ph,sp,c,k)=>{pp.push(P.x,P.y,P.z);pt.push(Tv.x,Tv.y,Tv.z);pph.push(ph);psp.push(sp);pc.push(c.r,c.g,c.b);pk.push(k)};
    const vc=[new THREE.Color('#9fd8ef'),new THREE.Color('#e7c6ec'),new THREE.Color('#d6e6f2')];
    for(let i=0;i<2600;i++){const u=rng(),P=onWall(u,rng()*6.283,.12+.8*Math.sqrt(rng())),T=curve.getTangentAt(clamp(u,0,1)).multiplyScalar(rand(1.2,2.4));add(P,T,rng(),rand(.03,.07),vc[i%3],1)}
    for(let i=0;i<110;i++){const u=rng(),P=onWall(u,rng()*6.283,.05+.4*rng());add(P,new V3(gauss(),gauss(),gauss()).multiplyScalar(.4),rng(),rand(.01,.03),new THREE.Color('#bcd6f5'),2)}
    const pg=new THREE.BufferGeometry();pg.setAttribute('position',new THREE.Float32BufferAttribute(pp,3));pg.setAttribute('aT',new THREE.Float32BufferAttribute(pt,3));
    pg.setAttribute('aP',new THREE.Float32BufferAttribute(pph,1));pg.setAttribute('aS',new THREE.Float32BufferAttribute(psp,1));
    pg.setAttribute('aC',new THREE.Float32BufferAttribute(pc,3));pg.setAttribute('aK',new THREE.Float32BufferAttribute(pk,1));
    g.add(Object.assign(new THREE.Points(pg,new THREE.ShaderMaterial({uniforms:partU,
      vertexShader:`uniform float uTime,uPix,uVel;attribute vec3 aT,aC;attribute float aP,aS,aK;varying vec3 vC;varying float vA,vK;
        void main(){float t=fract(aP+uTime*aS);vec3 p=position+aT*(t-.5);p+=vec3(sin(uTime*.7+aP*30.),cos(uTime*.53+aP*17.),sin(uTime*.41+aP*11.))*(aK<1.5?.06:.12);
          vec4 mv=modelViewMatrix*vec4(p,1.);float d=-mv.z;float life=smoothstep(0.,.18,t)*smoothstep(1.,.78,t),mv_=min(abs(uVel)*22.,1.);
          float near=aK>1.5?smoothstep(.15,.6,d)*smoothstep(7.,1.5,d):smoothstep(.25,1.6,d)*smoothstep(95.,8.,d);
          vA=life*near*(aK<1.5?.11+.18*mv_:.022);vC=aC;vK=aK;float sz=aK<1.5?1.+2.2*mv_:6.;
          gl_PointSize=min(sz*uPix*(18./max(d,.1)),(aK>1.5?44.:9.)*uPix);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`varying vec3 vC;varying float vA,vK;void main(){vec2 c=gl_PointCoord-.5;float d=length(c);if(d>.5)discard;
        float a=vK>1.5?exp(-d*d*9.)*(1.-smoothstep(.3,.5,d)):smoothstep(.5,.08,d);gl_FragColor=vec4(vC,a*vA);}`,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false}))}

  // ── pins: shards in brackets, LOCKED on the conversation strand (they do not drift); a checkpoint at the arch crown
  const pinsHere=M.pins.filter(p=>p.session===s.id&&p.type!=='checkpoint').slice(0,24);
  const ckHere=M.pins.filter(p=>p.session===s.id&&p.type==='checkpoint').slice(0,3);
  const pinU=p=>clamp(uOf(p.created),.04,.93);
  const pinBeads=pinsHere.map(p=>{const u=pinU(p),P=at(P0,0,u);const dir=P.clone().sub(curve.getPointAt(u)).normalize().negate();return {p,u,P,dir,world:P.clone().add(TUN_OFF)}});
  const crystals=pinBeads.map(b=>({pos:b.P,dir:b.dir,s:.16+.04*Math.sqrt(Math.max(1,b.p.links||1)),col:new THREE.Color(pinType(b.p.type).col),held:b.p.held?1:0}));
  const pinList=pinBeads.map(b=>({p:b.p,world:b.world,u:b.u}));
  ckHere.forEach((p,i)=>{const pos=P1.clone().addScaledVector(Ud,(.9+.1)*rad1+i*.7).addScaledVector(T1,-.3);
    crystals.push({pos,dir:Ud.clone(),s:.45,col:new THREE.Color(pinType('checkpoint').col),held:p.held?1:0});pinList.push({p,world:pos.clone().add(TUN_OFF),u:1})});
  if(crystals.length)g.add(pinSprites(crystals.map(c=>({pos:c.pos,col:c.col,held:c.held,s:c.s*.8})),{value:1}));

  // ── claims: the glyph (one glyph in every view; hover and selection read it)
  const threadU={...U,uSel:{value:-1},uSelOn:{value:0}};
  {const sP=[],sS=[],sL=[],sE=[],sI=[],sH=[],sC=[],sCh=[];
    stars.forEach(st=>{const gl=GLYPHS[st.li],c=new THREE.Color(CELL_COL[lmBest[st.li]]||'#8aa3b0');
      sP.push(st.p.x,st.p.y,st.p.z);sS.push(cellSize(LM[st.li]));sL.push(st.li);sE.push(...gl.ev);sI.push(...gl.info);sH.push(gl.hue.r,gl.hue.g,gl.hue.b);sC.push(c.r,c.g,c.b);
      sCh.push(LM[st.li].channel==null?-1:LM[st.li].channel)});
    const cg=new THREE.BufferGeometry();cg.setAttribute('position',new THREE.Float32BufferAttribute(sP,3));cg.setAttribute('aSize',new THREE.Float32BufferAttribute(sS,1));
    cg.setAttribute('aLm',new THREE.Float32BufferAttribute(sL,1));cg.setAttribute('aEv',new THREE.Float32BufferAttribute(sE,4));
    cg.setAttribute('aInfo',new THREE.Float32BufferAttribute(sI,4));cg.setAttribute('aHue',new THREE.Float32BufferAttribute(sH,3));cg.setAttribute('aCol',new THREE.Float32BufferAttribute(sC,3));
    cg.setAttribute('aChan',new THREE.Float32BufferAttribute(sCh,1));
    g.add(Object.assign(new THREE.Points(cg,new THREE.ShaderMaterial({uniforms:threadU,
      vertexShader:`uniform float uPix,uSel,uSelOn;attribute float aSize,aLm,aChan;attribute vec3 aCol,aHue;attribute vec4 aEv,aInfo;
        varying vec3 vC;varying float vA;varying vec4 vEv;varying vec4 vInfo;varying vec3 vHue;varying float vChan;
        void main(){vec4 mv=modelViewMatrix*vec4(position,1.);float d=-mv.z;float on=step(abs(aLm-uSel),.1);
          vC=aCol;vEv=aEv;vInfo=aInfo;vHue=aHue;vChan=aChan;vA=smoothstep(120.,14.,d)*smoothstep(.3,2.,d)*(.6+on*.4)*mix(1.,.35,uSelOn*(1.-on));
          gl_PointSize=min(aSize*1.6*(1.+on*.3)*uPix*(26./max(d,.1)),110.*uPix);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:GLYPH_FRAG,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false,renderOrder:4}))}
  const linked=new Set(M.edges.map(e=>e.a+'-'+e.b));
  // home: the cortex glows behind the entrance
  const Q0=curve.getPointAt(0),T0v=frameAt(0).T;const home=Q0.clone().addScaledVector(T0v,-60);
  const hs=new THREE.Sprite(new THREE.SpriteMaterial({map:GLOW,color:BRAND,transparent:true,opacity:.9,blending:THREE.AdditiveBlending,depthWrite:false}));
  hs.scale.setScalar(26);hs.position.copy(home);g.add(hs);
  // the doorways: a tall arch at the far end (the strands climb onto it) that opens onto the NEXT thread, and a small side
  // arch on the wall that takes you back to this thread's beginning
  const next=nextInThread(s);   // UX-PLAN 4.4: the far door leads on within the THREAD, not to any next strand
  const door=new THREE.Mesh(archGeo,doorMat(THREAD_COL,new THREE.Color(next?'#7fe8ff':'#f4fbff'),1));
  door.scale.setScalar(rad1);door.position.copy(P1);door.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(Rd,Ud,T1.clone().negate()));g.add(door);
  const backP=onWall(.9,Math.PI*.5+.9*TW,.92),backDoor=new THREE.Mesh(archGeo,doorMat(STRAND_COL,new THREE.Color('#f4fbff'),-1));
  backDoor.scale.setScalar(radius(.9)*.3);backDoor.position.copy(backP);backDoor.lookAt(curve.getPointAt(.9));g.add(backDoor);
  scene.add(g);rng=mulberry32(99);
  return {g,curve,frameAt,session:s,items,stars,gates,threadU,linked,sel:-1,stops:null,hl:null,strands:pairs,hlU,fibU,partU,tileU,pins:pinList,
    door:{mesh:door,world:P1.clone().add(TUN_OFF),next},back:{mesh:backDoor,world:backP.clone().add(TUN_OFF)},onWall};
}
// light an item and everything it is linked to (a message and its moments, or a moment and its turn)
function tunnelHighlight(it){
  const T=tunnel;if(!T||T.hl===it)return;T.hl=it;
  const H=T.hlU.value;H.forEach(v=>v.set(-1,0,0,0));let j=0;
  const put=(x,gain)=>{if(j<H.length)H[j++].set(x.bundle,x.ua-.003,x.ub+.003,gain)};
  if(it){put(it,2.4);it.links.slice(0,7).forEach(l=>put(l,2))}}   // the rungs show the link; no straight lines across the corridor
function disposeTunnel(){if(!tunnel)return;scene.remove(tunnel.g);tunnel.g.traverse(o=>{o.geometry?.dispose();o.material?.dispose?.()});tunnel=null;rail.build(null)}

// ═══════════════════════════════════════════════════════════════════════════
// 7b. SYNCHRONIZATION, inside the timeline (design §18.4; owner, 2026-10-19: "it does not need its own tab, it can
//     be part of the timeline"). Hover a session on the helix: every earlier step the memory handed to its steps
//     (RECALL_DELIVERED -> the DER chain row it names) arcs out of the session it came from and flows into this one,
//     and the strands stay until you hover another session, so you can move onto one and read it. Colour = where
//     the recall came from; solidity = whether it helped (RECALL_HELPED solid, no verdict an edge, RECALL_MISLED a
//     red desync). Click a strand to step into the session it came from.
// ═══════════════════════════════════════════════════════════════════════════
const REC_SRC={neighbors:{col:'#7fe8ff',word:'a similar earlier step'},prior_research:{col:'#ffcf6b',word:'earlier research'},
  chain_timeline:{col:'#f08ad6',word:'the timeline of this work'},known_case:{col:'#5dffb0',word:'a known case'}};
const prettyThread=t=>{const m=/^eval-(.+?)(-[0-9a-f]{6})?$/.exec(t||'');return m?'[eval] '+m[1].replace(/_/g,' '):String(t||'an earlier strand').slice(0,48)};
const sessOf=id=>id&&M.sById?M.sById.get(id):null;
const titleOf=id=>sessOf(id)?.objective||prettyThread(id);
// a point in time on the helix; what is older than the first session sinks below it (compressed)
const timeY=ts=>ts==null?-HELIX_H*1.1:ts<sT0?-HELIX_H-Math.min(.22*HELIX_H,Math.log1p((sT0-ts)/3600)*.5):helixY(clamp((ts-sT0)/Math.max(1,sT1-sT0),0,1));
const beadY=(id,ts)=>{const s=sessOf(id);return s?helixY(sessS(s)):timeY(ts)};
// every step of every turn that took memory, per session
const REC_BY=new Map();for(const t of (M.recalls||[]))for(const st of (t.steps||[])){if(!st.refs||!st.refs.length)continue;
  if(!REC_BY.has(t.session))REC_BY.set(t.session,{turns:new Set(),steps:[]});const e=REC_BY.get(t.session);e.turns.add(t.turn);e.steps.push(st)}
const recSummary=sid=>{const e=REC_BY.get(sid);if(!e)return null;const refs=e.steps.flatMap(st=>st.refs),helped=e.steps.filter(st=>st.outcome==='helped').length,
  misled=e.steps.filter(st=>st.outcome==='misled').length;return {steps:e.steps.length,refs:refs.length,from:new Set(refs.map(r=>r.session)).size,helped,misled}};
const syncG=new THREE.Group();syncG.visible=false;cortex.add(syncG);
const syncU={...U,uRes:{value:new THREE.Vector2(innerWidth,innerHeight)},uAsm:{value:0},uSel:{value:-1}};
const sync={sid:null,refs:[],hover:-1};
const SYNC_VS=`uniform float uTime,uAsm,uSel;uniform vec2 uRes;attribute vec3 aNx,aCol;attribute float aSide,aU,aW,aOut,aPh,aId;
  varying vec3 vC;varying float vA,vS;float h1(float x){return fract(sin(x*127.1)*43758.5453);}
  void main(){vec4 mv=modelViewMatrix*vec4(position,1.);vec4 c0=projectionMatrix*mv,c1=projectionMatrix*modelViewMatrix*vec4(position+aNx,1.);
    vec2 p0=c0.xy/max(c0.w,1e-4)*uRes*.5,p1=c1.xy/max(c1.w,1e-4)*uRes*.5,d=p1-p0;float sl=length(d);d=sl>1e-4?d/sl:vec2(1.,0.);
    float on=uSel<0.?1.:mix(.18,1.,step(abs(aId-uSel),.1)),sel=uSel<0.?0.:step(abs(aId-uSel),.1);
    c0.xy+=vec2(-d.y,d.x)*aW*(1.+sel*.6)*aSide/(uRes*.5)*c0.w;
    float drawn=step(aU,clamp(uAsm*1.5-aPh*.5,0.,1.));                         // each strand draws itself from its source
    float flow=pow(fract(aU*1.4-uTime*.3+aPh),12.);                          // memory travelling along the strand
    float mis=step(aOut,-.5),gz=mis*step(.82,h1(floor(uTime*5.)+aPh*31.));
    vC=mix(aCol,vec3(1.,.3,.32),mis*.6)*(1.+flow*1.5+gz*.8+sel*.6);
    vA=drawn*on*(aOut>.5?.34:aOut<-.5?.36:.18)*(1.+flow*.9)*smoothstep(0.,.05,aU)*smoothstep(1.,.97,aU);vS=aSide;gl_Position=c0;}`;
const SYNC_FS=`varying vec3 vC;varying float vA,vS;void main(){gl_FragColor=vec4(vC,vA*(1.-vS*vS));}`;
// fragments flying along each strand: the cubic is evaluated in the shader, so nothing moves on the CPU
const SYNCF_VS=`uniform float uTime,uPix,uAsm,uSel;attribute vec3 aP0,aC1,aC2,aP1,aCol;attribute float aPh,aSp,aOut,aId,aSize;
  varying vec3 vC;varying float vA,vSolid,vRot;
  void main(){float t=fract(uTime*aSp+aPh),s=1.-t;vec3 p=s*s*s*aP0+3.*s*s*t*aC1+3.*s*t*t*aC2+t*t*t*aP1;
    vec4 mv=modelViewMatrix*vec4(p,1.);float z=-mv.z;float on=uSel<0.?1.:mix(.2,1.,step(abs(aId-uSel),.1));
    vC=aCol;vSolid=aOut>.5?1.:aOut<-.5?.35:.12;vRot=aPh*6.2832+uTime*.4;
    vA=smoothstep(.95,1.,uAsm)*on*sin(3.1416*t)*.9;gl_PointSize=min(aSize*uPix*(40./max(z,.1)),20.*uPix);gl_Position=projectionMatrix*mv;}`;
function disposeSync(){syncG.traverse(o=>{if(o!==syncG){o.geometry?.dispose();o.material?.dispose?.()}});syncG.clear();sync.refs=[];sync.sid=null;sync.hover=-1}
function buildSyncFor(sid){
  if(sync.sid===sid)return;disposeSync();const e=REC_BY.get(sid);if(!e)return;sync.sid=sid;
  const s0=sessOf(sid),yT=s0?helixY(sessS(s0)):beadY(sid,e.steps[0]?.ts),P=new V3(0,yT,0);
  const rr=mulberry32(sid.split('').reduce((a,c)=>a*31+c.charCodeAt(0)|0,11));
  const RB={pos:[],nx:[],side:[],u:[],w:[],col:[],out:[],ph:[],id:[],idx:[]};
  const strand=(Ps,col,w,out,ph,id)=>{const n=Ps.length,base=RB.pos.length/3;
    for(let k=0;k<n;k++){const a=Ps[Math.max(0,k-1)],c=Ps[Math.min(n-1,k+1)];
      for(const sd of [-1,1]){RB.pos.push(Ps[k].x,Ps[k].y,Ps[k].z);RB.nx.push(c.x-a.x,c.y-a.y,c.z-a.z);RB.side.push(sd);RB.u.push(k/(n-1));RB.w.push(w);
        RB.col.push(col.r,col.g,col.b);RB.out.push(out);RB.ph.push(ph);RB.id.push(id)}}
    for(let k=0;k<n-1;k++){const j=base+2*k;RB.idx.push(j,j+1,j+2,j+1,j+3,j+2)}};
  const bez=(P0,C1,C2,P1,t)=>{const q=1-t;return P0.clone().multiplyScalar(q*q*q).addScaledVector(C1,3*q*q*t).addScaledVector(C2,3*q*t*t).addScaledVector(P1,t*t*t)};
  const angOf=id=>{let h=7;for(const c of String(id))h=h*31+c.charCodeAt(0)|0;return ((h>>>0)%3600)/3600*6.2832};
  const F={p0:[],c1:[],c2:[],p1:[],col:[],ph:[],sp:[],out:[],id:[],size:[]};
  e.steps.slice(-40).forEach(st=>{const out=st.outcome==='helped'?1:st.outcome==='misled'?-1:0,col=new THREE.Color((REC_SRC[st.source]||REC_SRC.neighbors).col);
    st.refs.forEach(r=>{const id=sync.refs.length,th=angOf(r.session||st.source)+(rr()-.5)*.5,dir=new V3(Math.cos(th),0,Math.sin(th));
      const S=new V3(0,beadY(r.session,r.ts),0),dy=yT-S.y;
      // an arc out of the helix and back in: a petal for a session just before, a long sweep for an old one
      // it arches over the helix and lands on this session from above, so it reads from the side as well as from above
      const out_=R*(.45+.45*Math.min(1,Math.abs(dy)/(R*1.4)))*(.85+.3*rr()),top=Math.max(S.y,P.y)+R*(.28+.12*rr())+Math.abs(dy)*.12;
      const C1=new V3(dir.x*out_,top,dir.z*out_),C2=new V3(dir.x*out_*.55,top,dir.z*out_*.55);
      const Ps=[];for(let q=0;q<=40;q++)Ps.push(bez(S,C1,C2,P,q/40));
      const ph=rr();strand(Ps,col,out===1?1.3:1,out,ph,id);
      F.p0.push(S.x,S.y,S.z);F.c1.push(C1.x,C1.y,C1.z);F.c2.push(C2.x,C2.y,C2.z);F.p1.push(P.x,P.y,P.z);F.col.push(col.r,col.g,col.b);
      F.ph.push(ph);F.sp.push(.14+.06*rr());F.out.push(out);F.id.push(id);F.size.push(1.4);
      sync.refs.push({r,st,pts:[.15,.3,.45,.6,.75].map(t=>bez(S,C1,C2,P,t))})})});
  const rg=new THREE.BufferGeometry();
  [['position',RB.pos,3],['aNx',RB.nx,3],['aSide',RB.side,1],['aU',RB.u,1],['aW',RB.w,1],['aCol',RB.col,3],['aOut',RB.out,1],['aPh',RB.ph,1],['aId',RB.id,1]]
    .forEach(([n,a,k])=>rg.setAttribute(n,new THREE.Float32BufferAttribute(a,k)));rg.setIndex(RB.idx);
  syncG.add(Object.assign(new THREE.Mesh(rg,new THREE.ShaderMaterial({uniforms:syncU,vertexShader:SYNC_VS,fragmentShader:SYNC_FS,transparent:true,
    depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide})),{frustumCulled:false}));
  if(F.p0.length){const fg=new THREE.BufferGeometry();fg.setAttribute('position',new THREE.Float32BufferAttribute(F.p0,3));
    [['aP0',F.p0,3],['aC1',F.c1,3],['aC2',F.c2,3],['aP1',F.p1,3],['aCol',F.col,3],['aPh',F.ph,1],['aSp',F.sp,1],['aOut',F.out,1],['aId',F.id,1],['aSize',F.size,1]]
      .forEach(([n,a,k])=>fg.setAttribute(n,new THREE.Float32BufferAttribute(a,k)));
    syncG.add(Object.assign(new THREE.Points(fg,new THREE.ShaderMaterial({uniforms:syncU,vertexShader:SYNCF_VS,fragmentShader:SHARD_FS,transparent:true,
      depthWrite:false,blending:THREE.AdditiveBlending})),{frustumCulled:false}))}
  syncU.uAsm.value=REDUCED?1:0;syncU.uSel.value=-1;
}
// over a strand of the session's recall: what that earlier step was, where it came from, what became of it
function syncHoverStrand(x,y){
  if(!sync.refs.length){syncU.uSel.value=-1;return false}
  const flat=sync.refs.flatMap(r=>r.pts),j=nearestScreen(flat,x,y,14),k=j<0?-1:Math.floor(j/5);syncU.uSel.value=k;sync.hover=k;if(k<0)return false;
  const {r,st}=sync.refs[k],src=REC_SRC[st.source]||REC_SRC.neighbors,at=flat[j],go=sessOf(r.session);if(go)canvas.style.cursor='pointer';
  setAnno('hover','sref'+sync.sid+k,()=>project(at),`<div class="k" style="color:${src.col}">${src.word} · given to step ${esc(st.step||'')}</div>
    <div class="t">${esc(r.did||'an earlier step')}</div><div class="m">from <em>${esc(titleOf(r.session))}</em>${r.ts?' · '+ago(r.ts):''}<br>
    ${r.tool&&r.tool!=='none'?esc(r.tool.replace(/_/g,' '))+' · ':''}${r.result==='success'?'it worked there':r.result?esc(r.result):'outcome unknown'}<br>
    ${st.outcome==='helped'?'the step it was given to was verified':st.outcome==='misled'?'<span class="w">the step it was given to failed</span>':'no verdict yet'}</div>
    ${go?'<span class="go">click · step into that strand</span>':''}`);return true}
function syncClick(){if(sync.hover<0)return false;const s=sessOf(sync.refs[sync.hover].r.session);if(s){enterTunnel(s);return true}return false}
function syncFrame(dt){const on=state.lens==='timeline'&&cam.mode==='orbit'&&!cam.tween&&sync.sid!=null;syncG.visible=on;if(!on)return;
  syncU.uRes.value.set(innerWidth,innerHeight);syncU.uAsm.value=Math.min(1,syncU.uAsm.value+dt/1.6)}

// ═══════════════════════════════════════════════════════════════════════════
// 8. the tissue: artifacts exhaled as an organic Voronoi mosaic (video 2)
// ═══════════════════════════════════════════════════════════════════════════
const tcv=document.getElementById('tissue'),tg=tcv.getContext('2d');
function makeThumb(kind,seed){
  const r=mulberry32(seed),Rr=(a,b)=>a+(b-a)*r(),P=a=>a[Math.floor(r()*a.length)];
  const c=document.createElement('canvas');c.width=c.height=256;const g=c.getContext('2d');
  const bg=(col)=>{g.fillStyle=col;g.fillRect(0,0,256,256)};
  if(kind==='code'){bg('#0b1118');let y=16;for(let i=0;i<17;i++){let x=12+Math.floor(Rr(0,4))*12;while(x<236&&r()<.82){const w=Rr(8,44);
    g.globalAlpha=.85;g.fillStyle=P(['#7fd1ff','#c792ea','#ffcb6b','#89ddff','#a5e075','#5d6b78','#5d6b78']);g.fillRect(x,y,w,6);x+=w+6}y+=14}}
  else if(kind==='terminal'){bg('#050607');g.font='11px monospace';let y=20;for(let i=0;i<15;i++){const ok=r()<.8;
    g.fillStyle=i%4===0?'#8aa':ok?'#5dffb0':'#ff6a4a';g.fillText(i%4===0?'> pytest -x tests/'+P(['turn','ledger','oracle']):(ok?'PASSED  ':'FAILED  ')+P(['test_turn_end','test_lane_order','test_bar','test_store']),10,y);y+=15}}
  else if(kind==='chart'){bg('#0a0f14');g.strokeStyle='rgba(120,160,190,.18)';for(let i=1;i<6;i++){g.beginPath();g.moveTo(16,i*42);g.lineTo(240,i*42);g.stroke()}
    if(r()<.5){for(let i=0;i<11;i++){const h=Rr(20,190);g.fillStyle=i===7?'#00d4ff':'#2a6f8a';g.fillRect(22+i*20,236-h,13,h)}}
    else{g.strokeStyle='#00d4ff';g.lineWidth=2.5;g.beginPath();let y=Rr(80,180);for(let x=16;x<=240;x+=8){y=clamp(y+Rr(-18,18),30,230);x===16?g.moveTo(x,y):g.lineTo(x,y)}g.stroke()}}
  else if(kind==='screen'){bg('#0d1117');g.fillStyle='#161c24';g.fillRect(0,0,256,26);g.fillRect(0,26,58,230);
    for(let i=0;i<5;i++){g.fillStyle='#1d2530';g.fillRect(70,38+i*42,172,32);g.fillStyle='rgba(0,212,255,.6)';g.fillRect(78,48+i*42,Rr(30,120),4)}
    const gr=g.createRadialGradient(200,200,0,200,200,40);gr.addColorStop(0,'rgba(0,212,255,.9)');gr.addColorStop(1,'rgba(0,212,255,0)');g.fillStyle=gr;g.fillRect(150,150,100,100)}
  else if(kind==='doc'){bg('#e8e4dc');g.fillStyle='#22262b';g.fillRect(24,26,Rr(110,190),11);g.fillStyle='#8b8f94';
    for(let i=0;i<14;i++)g.fillRect(24,56+i*13,i%5===4?Rr(60,140):Rr(170,208),4)}
  else if(kind==='web'){bg('#f4f5f7');g.fillStyle=P(['#3a5bd9','#1f8a70','#c2410c','#7c3aed']);g.fillRect(0,0,256,30);
    const gr=g.createLinearGradient(0,40,256,140);gr.addColorStop(0,`hsl(${Rr(0,360)},55%,60%)`);gr.addColorStop(1,`hsl(${Rr(0,360)},45%,35%)`);g.fillStyle=gr;g.fillRect(16,42,224,96);
    g.fillStyle='#9aa0a6';for(let i=0;i<7;i++)g.fillRect(16,152+i*13,Rr(120,224),4)}
  else if(kind==='video'){const h=Rr(180,320),gr=g.createLinearGradient(0,0,256,256);gr.addColorStop(0,`hsl(${h},45%,30%)`);gr.addColorStop(1,`hsl(${h+50},55%,12%)`);
    g.fillStyle=gr;g.fillRect(0,0,256,256);g.fillStyle='rgba(0,0,0,.35)';g.fillRect(0,0,256,26);g.fillRect(0,222,256,34);
    g.fillStyle='rgba(255,255,255,.85)';g.beginPath();g.moveTo(108,96);g.lineTo(108,160);g.lineTo(160,128);g.closePath();g.fill();
    g.fillStyle='rgba(255,255,255,.25)';g.fillRect(16,236,224,4);g.fillStyle='#ff5fd6';g.fillRect(16,236,Rr(40,200),4)}
  else if(kind==='audio'){bg('#07090c');for(let x=10;x<246;x+=5){const h=Math.abs(Math.sin(x*.05+Rr(0,1)))*Rr(10,90);g.fillStyle='rgba(0,212,255,.8)';g.fillRect(x,128-h,3,h*2)}}
  else{const h=Rr(0,360);const gr=g.createLinearGradient(0,0,0,256);gr.addColorStop(0,`hsl(${h},60%,62%)`);gr.addColorStop(1,`hsl(${h+40},50%,22%)`);g.fillStyle=gr;g.fillRect(0,0,256,256);
    g.fillStyle=`hsla(${h+180},80%,80%,.9)`;g.beginPath();g.arc(Rr(60,200),Rr(50,110),Rr(14,30),0,7);g.fill();
    for(let k=0;k<3;k++){g.fillStyle=`hsla(${h+20},40%,${16+k*7}%,1)`;g.beginPath();g.moveTo(0,256);let y=Rr(130,190)+k*20;
      for(let x=0;x<=256;x+=16){y+=Rr(-14,14);g.lineTo(x,y)}g.lineTo(256,256);g.fill()}}
  g.globalAlpha=1;return c}
// Layered: formats (images, videos, audio, documents, code ...) -> folders -> the things themselves.
// Strands in the tunnel's block style run from the orb to every cell: one strand per thread a thing
// was made in, ending in a creation knot at the thing. Hover a strand to see its thread; click it
// to step into that thread.
const FORMAT_OF={image:'images',screen:'images',video:'videos',audio:'audio',doc:'documents',code:'code',web:'web captures',chart:'charts',terminal:'test runs'};
const FORMAT_ORDER=['images','videos','audio','documents','code','web captures','charts','test runs'];
const thumbCache=new Map();const thumbOf=a=>{if(!thumbCache.has(a.id))thumbCache.set(a.id,makeThumb(a.kind,a.seed||1));return thumbCache.get(a.id)};
const tissue={on:false,t:0,cells:[],hover:-1,focus:-1,cx:0,cy:0,rad:200,path:[],threads:[],hoverThread:-1,crumbs:[],lvlT:1};
function tissueNodes(){const P=tissue.path;
  const arts=M.artifacts.filter(a=>(!P[0]||FORMAT_OF[a.kind]===P[0])&&(!P[1]||(a.folder||'unsorted')===P[1]));
  if(P.length>=2)return arts.map(a=>({type:'item',a,items:[a],w:a.weight||1,label:a.name}));
  const key=P.length===0?(a=>FORMAT_OF[a.kind]||'other'):(a=>a.folder||'unsorted');const m=new Map();
  arts.forEach(a=>{const k=key(a);if(!m.has(k))m.set(k,[]);m.get(k).push(a)});
  const keys=[...m.keys()].sort((x,y)=>P.length===0?FORMAT_ORDER.indexOf(x)-FORMAT_ORDER.indexOf(y):m.get(y).length-m.get(x).length);
  return keys.map(k=>({type:'group',label:k,items:m.get(k).sort((x,y)=>y.ts-x.ts),w:.8+Math.sqrt(m.get(k).length)*1.4}))}
function setTissueLevel(path,from){tissue.path=path;tissue.focus=-1;tissue.hover=-1;tissue.hoverThread=-1;clearAnno('focus');clearAnno('hover');
  const nodes=tissueNodes(),n=nodes.length;
  tissue.cells=nodes.map((nd,i)=>{const r=Math.sqrt((i+.5)/n)*tissue.rad*.8,th=i*2.39996;
    const x=from?from.x+gauss()*8:tissue.cx+Math.cos(th)*r,y=from?from.y+gauss()*8:tissue.cy+Math.sin(th)*r;
    return {...nd,x,y,sx:tissue.cx+gauss()*tissue.rad*.9,sy:tissue.cy+gauss()*tissue.rad*.7,wt:nd.w,poly:null}});
  tissue.lvlT=from?0:1;buildTissueThreads()}
function buildTissueThreads(){const by=new Map();
  tissue.cells.forEach((c,ci)=>c.items.forEach(a=>{if(!a.session)return;if(!by.has(a.session))by.set(a.session,{cells:new Set(),n:0});const t=by.get(a.session);t.cells.add(ci);t.n++}));
  tissue.threads=[...by.entries()].map(([sid,t])=>({sid,s:M.sById.get(sid),cells:[...t.cells],n:t.n})).filter(t=>t.s)
    .sort((a,b)=>b.s.started-a.s.started).slice(0,22).map((t,i)=>({...t,hue:(300+i*37)%360,pts:[]}))}
function initTissue(){layoutTissue(false);setTissueLevel([],null)}
function layoutTissue(reset){
  const c=project(new V3(-2.3*R,0,0)),e=project(new V3(-2.3*R+1.35*R,0,0));
  tissue.rad=Math.max(120,Math.min(Math.abs(e.x-c.x),innerHeight*.4,innerWidth*.4));
  tissue.cx=Math.max(c.x,tissue.rad+24);tissue.cy=c.y+10;
  if(reset)setTissueLevel(tissue.path,null)}
function clipConvex(poly,clip){let out=poly;for(let i=0;i<clip.length;i++){const A=clip[i],B=clip[(i+1)%clip.length];const inp=out;out=[];if(!inp.length)break;
  const side=p=>(B[0]-A[0])*(p[1]-A[1])-(B[1]-A[1])*(p[0]-A[0]);
  for(let j=0;j<inp.length;j++){const P=inp[j],Q=inp[(j+1)%inp.length];const sp=side(P),sq=side(Q);
    if(sp>=0)out.push(P);if((sp>=0)!==(sq>=0)){const t=sp/(sp-sq);out.push([P[0]+(Q[0]-P[0])*t,P[1]+(Q[1]-P[1])*t])}}}return out}
function chaikin(p,it){for(let k=0;k<it;k++){const q=[];for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length];
  q.push([a[0]*.75+b[0]*.25,a[1]*.75+b[1]*.25],[a[0]*.25+b[0]*.75,a[1]*.25+b[1]*.75])}p=q}return p}
// a strand of small faceted blocks along a quadratic curve (the tunnel's language, flattened)
function blockStrand(x0,y0,cx,cy,x1,y1,hue,alpha,size,store,knot){
  const len=Math.hypot(cx-x0,cy-y0)+Math.hypot(x1-cx,y1-cy),n=Math.max(4,Math.floor(len/(7*size)));
  for(let i=0;i<n;i++){const t=(i+.5)/n,u=1-t;
    const x=u*u*x0+2*u*t*cx+t*t*x1,y=u*u*y0+2*u*t*cy+t*t*y1,dx=2*u*(cx-x0)+2*t*(x1-cx),dy=2*u*(cy-y0)+2*t*(y1-cy);
    // two staggered rows of small hex cells: the tunnel's honeycomb ribbon, flattened
    const light=50+((i*7919)%5)*6,nx=-dy/(Math.hypot(dx,dy)||1),ny=dx/(Math.hypot(dx,dy)||1);
    for(const side of [-1,1]){const hx=x+nx*side*2.2*size+(side>0?dx:0)/(Math.hypot(dx,dy)||1)*1.8*size,hy=y+ny*side*2.2*size+(side>0?dy:0)/(Math.hypot(dx,dy)||1)*1.8*size;
      tg.beginPath();for(let v=0;v<6;v++){const a=v/6*6.2832+Math.PI/6;tg.lineTo(hx+Math.cos(a)*2.1*size,hy+Math.sin(a)*2.1*size)}tg.closePath();
      tg.fillStyle=`hsla(${hue},80%,${light}%,${alpha*.45})`;tg.fill();tg.strokeStyle=`hsla(${hue},95%,82%,${alpha*.8})`;tg.lineWidth=.8;tg.stroke()}
    if(store&&i%2===0)store.push([x,y])}
  if(knot){tg.save();tg.translate(x1,y1);tg.fillStyle=`hsla(${hue},95%,82%,${Math.min(1,alpha*1.4)})`;tg.fillRect(-5*size,-3*size,10*size,6*size);
    tg.strokeStyle=`hsla(${hue},95%,90%,${alpha})`;tg.beginPath();tg.arc(0,0,8*size,0,7);tg.stroke();tg.restore()}}
function drawTissue(dt){
  const W=innerWidth,H=innerHeight;if(tcv.width!==W*DPR){tcv.width=W*DPR;tcv.height=H*DPR}
  tg.setTransform(DPR,0,0,DPR,0,0);tg.clearRect(0,0,W,H);
  if(!tissue.on&&tissue.t<=0)return;
  const curT=cursorNow()?null:cursorTs();
  tissue.t=clamp(tissue.t+dt*(tissue.on?.75:-1.6),0,1);tissue.lvlT=Math.min(1,tissue.lvlT+dt*1.6);
  const cells=tissue.cells,n=cells.length;if(!n)return;
  const el=clock.elapsedTime;
  const hotThread=tissue.hoverThread>=0?tissue.threads[tissue.hoverThread]:null;
  cells.forEach((c,i)=>{const lit=hotThread&&hotThread.cells.includes(i);
    c.wt=c.w*(i===tissue.hover?2.4:1)*(lit?1.6:1)*(tissue.focus===i?26:1)*(tissue.focus>=0&&tissue.focus!==i?.55:1);c.ww=lerp(c.ww??c.w,c.wt,Math.min(1,dt*5))});
  const sumW=cells.reduce((a,c)=>a+c.ww,0);
  for(let it=0;it<2;it++){
    for(let i=0;i<n;i++){const a=cells[i],ra=tissue.rad*Math.sqrt(a.ww/sumW)*.95;
      for(let j=i+1;j<n;j++){const b=cells[j],rb=tissue.rad*Math.sqrt(b.ww/sumW)*.95;let dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||.01;
        const want=ra+rb;if(d<want){const f=(want-d)*.25/d;dx*=f;dy*=f;const sa=b.ww/(a.ww+b.ww),sb=a.ww/(a.ww+b.ww);a.x-=dx*sa;a.y-=dy*sa;b.x+=dx*sb;b.y+=dy*sb}}
      let dx=a.x-tissue.cx,dy=a.y-tissue.cy,d=Math.hypot(dx,dy)||.01;const lim=tissue.rad-ra*.6;
      if(d>lim){a.x-=dx/d*(d-lim)*.3;a.y-=dy/d*(d-lim)*.3}
      if(n>1){a.x+=Math.sin(el*.4+i)*.08;a.y+=Math.cos(el*.35+i*1.3)*.08}}}
  const fly=clamp(tissue.t/.55,0,1),grow=clamp((tissue.t-.42)/.58,0,1)*tissue.lvlT;
  if(tissue.t<1){cells.forEach(c=>{const e=easeIO(fly),x=lerp(c.sx,c.x,e),y=lerp(c.sy,c.y,e),s=lerp(5,16,e);
      tg.globalAlpha=(1-grow)*Math.min(1,tissue.t*4);tg.drawImage(thumbOf(c.items[0]),x-s/2,y-s/2,s,s)})}
  if(grow<=0)return;
  // cells
  let polys=[];
  if(n===1){const c=cells[0];const p=[];for(let k=0;k<64;k++){const a=k/64*6.283;p.push([tissue.cx+Math.cos(a)*tissue.rad*.98,tissue.cy+Math.sin(a)*tissue.rad*.98])}
    c.poly=p;c.cx=tissue.cx;c.cy=tissue.cy}
  else{const del=Delaunay.from(cells.map(c=>[c.x,c.y]));
    const vor=del.voronoi([tissue.cx-tissue.rad*1.3,tissue.cy-tissue.rad*1.3,tissue.cx+tissue.rad*1.3,tissue.cy+tissue.rad*1.3]);
    const circ=[];for(let k=0;k<72;k++){const a=k/72*6.283;const rr=tissue.rad*(1+.025*Math.sin(a*5+el*.6));circ.push([tissue.cx+Math.cos(a)*rr,tissue.cy+Math.sin(a)*rr])}
    cells.forEach((c,i)=>{let poly=vor.cellPolygon(i);if(!poly){c.poly=null;return}poly=clipConvex(poly.slice(0,-1),circ);if(poly.length<3){c.poly=null;return}
      let cx=0,cy=0;poly.forEach(p=>{cx+=p[0];cy+=p[1]});cx/=poly.length;cy/=poly.length;
      poly=poly.map(p=>{const dx=cx-p[0],dy=cy-p[1],d=Math.hypot(dx,dy)||1;const k=Math.min(.45,2.4/d);return [p[0]+dx*k,p[1]+dy*k]});
      c.poly=chaikin(poly,2);c.cx=cx;c.cy=cy})}
  cells.forEach((c,i)=>{const poly=c.poly;if(!poly)return;
    let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;poly.forEach(p=>{x0=Math.min(x0,p[0]);y0=Math.min(y0,p[1]);x1=Math.max(x1,p[0]);y1=Math.max(y1,p[1])});
    const s=Math.max(x1-x0,y1-y0),dim=(tissue.focus>=0&&tissue.focus!==i)||(hotThread&&!hotThread.cells.includes(i));
    const later=curT!=null&&c.items.every(a=>(a.ts||0)>curT);   // made after the time cursor
    tg.save();tg.globalAlpha=grow*(dim?.45:1)*(later?.14:1);tg.beginPath();poly.forEach((p,k)=>k?tg.lineTo(p[0],p[1]):tg.moveTo(p[0],p[1]));tg.closePath();tg.clip();
    if(c.type==='item')tg.drawImage(thumbOf(c.a),(x0+x1)/2-s/2,(y0+y1)/2-s/2,s,s);
    else{const th=c.items.slice(0,4),gw=(x1-x0)/2,gh=(y1-y0)/2;th.forEach((a,k)=>{const tx=x0+(k%2)*gw,ty=y0+Math.floor(k/2)*gh,ts=Math.max(gw,gh);
        tg.drawImage(thumbOf(a),tx+gw/2-ts/2,ty+gh/2-ts/2,ts,ts)});if(th.length===1)tg.drawImage(thumbOf(th[0]),(x0+x1)/2-s/2,(y0+y1)/2-s/2,s,s);
      tg.fillStyle='rgba(2,4,8,.55)';tg.fillRect(x0,y0,x1-x0,y1-y0)}
    const vg=tg.createRadialGradient(c.cx,c.cy,s*.2,c.cx,c.cy,s*.75);vg.addColorStop(0,'rgba(2,3,6,0)');vg.addColorStop(1,i===tissue.hover?'rgba(2,3,6,.12)':'rgba(2,3,6,.5)');
    tg.fillStyle=vg;tg.fillRect(x0,y0,x1-x0,y1-y0);tg.restore();
    tg.save();tg.globalAlpha=grow*(i===tissue.hover||i===tissue.focus?.9:.25);tg.strokeStyle=i===tissue.hover||i===tissue.focus?'#f4fbff':THEMES[themeIdx][1];
    tg.beginPath();poly.forEach((p,k)=>k?tg.lineTo(p[0],p[1]):tg.moveTo(p[0],p[1]));tg.closePath();tg.stroke();tg.restore();
    if(c.type==='group'&&s>46){tg.save();tg.globalAlpha=grow;tg.textAlign='center';tg.textBaseline='middle';tg.shadowColor='#000';tg.shadowBlur=8;
      tg.fillStyle='#ffffff';tg.font=`400 ${clamp(s*.11,12,19)}px "Inter Tight", sans-serif`;tg.fillText(c.label,c.cx,c.cy-6);
      tg.fillStyle='#c3d6df';tg.font='10.5px "JetBrains Mono", monospace';tg.fillText(`${c.items.length} ${c.items.length===1?'thing':'things'} · open`,c.cx,c.cy+12);tg.restore()}});
  // breadcrumb: where you are in the layers
  tg.save();tg.font='11px "JetBrains Mono", monospace';tg.textBaseline='middle';tg.textAlign='left';
  const crumbs=['things made',...tissue.path];let x=tissue.cx-tissue.rad,y=tissue.cy-tissue.rad-26;tissue.crumbs=[];
  crumbs.forEach((c,k)=>{const last=k===crumbs.length-1,w=tg.measureText(c).width;tg.fillStyle=last?'#f4fbff':'#8fb0bf';tg.shadowColor='#000';tg.shadowBlur=6;tg.fillText(c,x,y);
    tissue.crumbs.push({x,y,w,k});x+=w;if(!last){tg.fillStyle='#4d6573';tg.fillText('  ›  ',x,y);x+=tg.measureText('  ›  ').width}});
  if(tissue.path.length){tg.fillStyle='#4d6573';tg.fillText('   esc · up a layer',x,y)}
  tg.restore();tg.globalAlpha=1}
function tissueHit(x,y){const cs=tissue.cells;for(let i=0;i<cs.length;i++){const p=cs[i].poly;if(!p)continue;let ins=false;
  for(let a=0,b=p.length-1;a<p.length;b=a++){if((p[a][1]>y)!==(p[b][1]>y)&&x<(p[b][0]-p[a][0])*(y-p[a][1])/(p[b][1]-p[a][1])+p[a][0])ins=!ins}if(ins)return i}return -1}
function threadHit(){return -1} // things made carry no strands; a focused item links to its thread
function crumbHit(x,y){return tissue.crumbs.find(c=>x>=c.x&&x<=c.x+c.w&&Math.abs(y-c.y)<9)}
function tissueUp(){if(tissue.focus>=0){tissue.focus=-1;clearAnno('focus');return true}
  if(tissue.path.length){setTissueLevel(tissue.path.slice(0,-1),null);return true}return false}

// ═══════════════════════════════════════════════════════════════════════════
// 9. camera: orbit (outside), fly (inside the brain), tunnel (inside a session)
// ═══════════════════════════════════════════════════════════════════════════
const clock=new THREE.Clock();
const cam={mode:'orbit',target:new V3(),targetT:new V3(),az:.7,el:.16,dist:58,azT:.7,elT:.16,distT:58,fov:38,fovT:38,
  yaw:0,pitch:0,yawT:0,pitchT:0,lean:new THREE.Vector2(),roll:0,pos:new V3(),vel:new V3(),tp:0,tpT:0,tween:null,look:new V3(),idle:0};
const mouse={x:innerWidth/2,y:innerHeight/2,nx:0,ny:0,down:false,dragged:0,lx:0,ly:0};
function tweenTo(pos,look,fov,dur,done){cam.tween={p0:camera.position.clone(),l0:cam.look.clone(),f0:camera.fov,p1:pos.clone(),l1:look.clone(),f1:fov,
  t:0,dur:REDUCED?.01:dur,done}}
// one continuous flight along a spline (position and gaze each follow their own curve); onT(e)
// lets a transition drive scene state (the aperture) from the same progress, so nothing pops
function tweenPath(pts,looks,fov,dur,{done=null,onT=null,kick=0}={}){
  cam.tween={path:new THREE.CatmullRomCurve3(pts,false,'centripetal'),lpath:new THREE.CatmullRomCurve3(looks,false,'centripetal'),
    f0:camera.fov,f1:fov,t:0,dur:REDUCED?.01:dur,done,onT,kick}}
// points on a great circle from the camera's side of the orb round to a region, so a flight to a
// region on the far side swings round the orb instead of cutting through it
function arcTo(from,toDir,r1,n){const d0=from.clone().normalize(),r0=from.length(),q=new THREE.Quaternion().setFromUnitVectors(d0,toDir),out=[];
  for(let k=1;k<=n;k++){const qk=new THREE.Quaternion().slerp(q,k/n);out.push(d0.clone().applyQuaternion(qk).multiplyScalar(lerp(r0,r1,k/n)))}return out}
function orbitFrom(pos,target){const d=pos.clone().sub(target);cam.dist=cam.distT=d.length();cam.az=cam.azT=Math.atan2(d.x,d.z);
  cam.el=cam.elT=Math.asin(clamp(d.y/cam.dist,-1,1));cam.target.copy(target);cam.targetT.copy(target);cam.par=0}
function flyFrom(pos,look){cam.pos.copy(pos);const d=look.clone().sub(pos).normalize();cam.yaw=cam.yawT=Math.atan2(d.x,d.z);cam.pitch=cam.pitchT=Math.asin(clamp(d.y,-1,1));
  cam.vel.set(0,0,0);cam.lean.set(0,0);cam.roll=0;cam.pyaw=cam.yaw;cam.idle=0}
const dirOf=(yaw,pitch)=>new V3(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch));
const keys={};
const __cortex={scene,renderer,composer,bloom,cortex,camera,project:v=>project(v),cam,mouse,keys,get state(){return state},M,IMM,get tunnel(){return tunnel},setLens:l=>setLens(l),enter:i=>enterTunnel(sess[i]),
  dive:i=>dive(i),immune:q=>immuneSignal(q),pins:()=>pinInfo,nodes:()=>NDS.length,spaces:()=>SPACES.length,sync:()=>sync,syncFor:id=>buildSyncFor(id)}; // inspection handle for the mockup
const angWrap=a=>{a=(a+Math.PI)%(Math.PI*2);if(a<0)a+=Math.PI*2;return a-Math.PI};
function updateCamera(dt){
  if(cam.tween){const tw=cam.tween;tw.t+=dt/tw.dur;const e=easeIO(Math.min(1,tw.t));
    if(tw.path){camera.position.copy(tw.path.getPoint(e));cam.look.copy(tw.lpath.getPoint(e))}
    else{camera.position.lerpVectors(tw.p0,tw.p1,e);cam.look.lerpVectors(tw.l0,tw.l1,e)}
    camera.fov=lerp(tw.f0,tw.f1,e)+Math.sin(e*Math.PI)*(tw.kick||0);
    camera.lookAt(cam.look);camera.updateProjectionMatrix();tw.onT&&tw.onT(e);
    if(tw.t>=1){cam.tween=null;tw.done&&tw.done()}return}
  if(cam.mode==='orbit'){
    cam.idle+=dt;if(!REDUCED&&cam.idle>4&&state.lens==='cortex'&&!state.diving)cam.azT+=dt*.035;
    const k=1-Math.pow(.0015,dt);cam.az=lerp(cam.az,cam.azT,k);cam.el=lerp(cam.el,cam.elT,k);cam.dist=lerp(cam.dist,cam.distT,k);cam.target.lerp(cam.targetT,k);
    cam.par=Math.min(1,(cam.par??1)+dt*.6); // mouse parallax eases back in after a flight
    const az=cam.az+mouse.nx*.08*cam.par,el=cam.el+mouse.ny*.05*cam.par;
    camera.position.set(cam.target.x+Math.sin(az)*Math.cos(el)*cam.dist,cam.target.y+Math.sin(el)*cam.dist,cam.target.z+Math.cos(az)*Math.cos(el)*cam.dist);
    cam.look.copy(cam.target);camera.lookAt(cam.look)}
  else if(cam.mode==='fly'){
    // Inside the mind you SWIM, you are not on a tripod: the gaze eases after the drag and leans toward the pointer,
    // movement keeps its momentum, the view banks into a turn and breathes a little; left alone, a slow current carries
    // you round the core (or round the thought you opened) until you take over again.
    cam.idle+=dt;const t=clock.elapsedTime,ek=1-Math.pow(.003,dt);
    cam.yaw=lerp(cam.yaw,cam.yawT,ek);cam.pitch=lerp(cam.pitch,cam.pitchT,ek);
    const lk=1-Math.pow(.08,dt),free=mouse.down?0:1;cam.lean.x=lerp(cam.lean.x,-mouse.nx*.22*free,lk);cam.lean.y=lerp(cam.lean.y,mouse.ny*.15*free,lk);
    const fwd=dirOf(cam.yaw+cam.lean.x,clamp(cam.pitch+cam.lean.y,-1.45,1.45));
    const right=new V3().crossVectors(fwd,new V3(0,1,0)).normalize(),up=new V3().crossVectors(right,fwd);
    const A=R*2.4*dt;if(keys.w||keys.arrowup)cam.vel.addScaledVector(fwd,A);if(keys.s||keys.arrowdown)cam.vel.addScaledVector(fwd,-A);
    if(keys.a||keys.arrowleft)cam.vel.addScaledVector(right,-A);if(keys.d||keys.arrowright)cam.vel.addScaledVector(right,A);
    if(keys.e||keys[' '])cam.vel.y+=A;if(keys.q||keys.shift)cam.vel.y-=A;
    if(!REDUCED&&cam.idle>3){const w=smooth01((cam.idle-3)/4),piv=state.focusSoma>=0?somaWorld(state.focusSoma):new V3();
      const rel=cam.pos.clone().sub(piv),tan=new V3(0,1,0).cross(rel);
      if(tan.lengthSq()>1e-6){tan.normalize();cam.pos.addScaledVector(tan,R*(state.focusSoma>=0?.05:.04)*w*dt);cam.pos.y+=Math.sin(t*.35)*R*.006*w*dt}
      if(state.focusSoma>=0){const d=piv.clone().sub(cam.pos).normalize();cam.yawT=cam.yaw+angWrap(Math.atan2(d.x,d.z)-cam.yaw)*Math.min(1,dt*1.5*w);
        cam.pitchT=lerp(cam.pitchT,Math.asin(clamp(d.y,-1,1)),Math.min(1,dt*1.5*w))}
      else cam.yawT+=.05*w*dt}
    cam.pos.addScaledVector(cam.vel,dt);cam.vel.multiplyScalar(Math.pow(.12,dt));
    // the wall of the mind is soft: you slow as you near it instead of hitting a stop
    {const l=cam.pos.length(),n=cam.pos.clone().divideScalar(Math.max(l,1e-6)),out=cam.vel.dot(n);
      if(l>R*.82&&out>0)cam.vel.addScaledVector(n,-out*Math.min(1,(l-R*.82)/(R*.1)));if(l>R*.94)cam.pos.multiplyScalar(R*.94/l)}
    const sw=.006*(1-.6*(state.focusSoma>=0)),sx=(Math.sin(t*.37)+.5*Math.sin(t*.91))*sw,sy=(Math.sin(t*.29+1)+.5*Math.sin(t*.77))*sw;
    camera.position.copy(cam.pos);cam.look.copy(cam.pos).add(fwd).addScaledVector(right,sx).addScaledVector(up,sy);camera.lookAt(cam.look);
    const yv=angWrap(cam.yaw-(cam.pyaw??cam.yaw))/Math.max(dt,1e-3);cam.pyaw=cam.yaw;
    cam.roll=lerp(cam.roll,clamp(yv*.07-cam.vel.dot(right)*.012,-.14,.14),1-Math.pow(.04,dt));camera.rotateZ(cam.roll)}
  else if(cam.mode==='tunnel'&&tunnel){
    // a label under the pointer (a moment, a claim, a pin, a doorway) HOLDS the corridor: what is being read stays put
    // (owner, 2026-10-24). Travel the user asks for - the wheel, w/s, a click on a stop - still moves it.
    const held=slots.hover?.on&&cam.idle>.6&&!(keys.w||keys.s||keys.arrowup||keys.arrowdown);
    if(held)cam.tpT=cam.tp;
    else if(!REDUCED&&cam.idle>2.5&&!tunnel.stops)cam.tpT+=dt*.0035; // no drift while following a thread
    cam.idle+=dt;
    if(keys.w||keys.arrowup)cam.tpT+=dt*.05;if(keys.s||keys.arrowdown)cam.tpT-=dt*.05;
    cam.tpT=clamp(cam.tpT,0,.985);cam.tp=lerp(cam.tp,cam.tpT,1-Math.pow(.02,dt));
    if(tunnel.partU){const v=(cam.tp-(tunnel.ptp??cam.tp))/Math.max(dt,1e-3);tunnel.ptp=cam.tp;tunnel.partU.uVel.value+=(v-tunnel.partU.uVel.value)*.12}  // travel speed: the vesicles streak
    // entering is synchronizing (design §18): a pale void that clears while the corridor's fragments fly together
    {const A=tunnel.tileU.uAsm;A.value=Math.min(1,A.value+dt/1.6);tunnel.fibU.uRes.value.set(innerWidth,innerHeight);
      if(state.voidT>0){state.voidT=Math.max(0,state.voidT-dt/1.3);voidCol.copy(DARK).lerp(VOID,smooth01(state.voidT));renderer.setClearColor(voidCol,1)}}
    // THE VIEW. The camera rides the corridor's centre line and looks where the corridor GOES (a point further along
    // the curve), not along the local tangent - so the far opening stays near the middle of the screen through a bend.
    // The gaze eases into a bend instead of snapping, leans a little toward the pointer in SCREEN axes (the old lean used
    // the Frenet normals, which twist along a near-straight curve: the same pointer turned the view a different way as
    // you travelled), and banks gently into the bend.
    const C=tunnel.curve,CL=tunnel.CL??=C.getLength(),P=C.getPointAt(cam.tp).add(TUN_OFF),T=C.getTangentAt(cam.tp);
    const aimDir=C.getPointAt(Math.min(1,cam.tp+26/CL)).add(TUN_OFF).sub(P);
    if(aimDir.lengthSq()<1)aimDir.copy(T);aimDir.normalize();
    const dk=1-Math.pow(.02,dt);tunnel.dir=tunnel.dir?tunnel.dir.lerp(aimDir,dk).normalize():aimDir.clone();
    const fwd=tunnel.dir,right=new V3().crossVectors(fwd,UP).normalize(),up=new V3().crossVectors(right,fwd);
    const lk=1-Math.pow(.08,dt);cam.lean.x=lerp(cam.lean.x,mouse.nx*.12,lk);cam.lean.y=lerp(cam.lean.y,mouse.ny*.08,lk);
    const t=clock.elapsedTime,sw=held?0:.004,sx=(Math.sin(t*.37)+.5*Math.sin(t*.91))*sw,sy=(Math.sin(t*.29+1)+.5*Math.sin(t*.77))*sw;
    const Q=P.clone().addScaledVector(fwd,20).addScaledVector(right,20*(cam.lean.x+sx)).addScaledVector(up,20*(cam.lean.y+sy));
    const lat=aimDir.dot(new V3().crossVectors(T,UP).normalize());   // how far the corridor ahead turns sideways
    cam.roll=lerp(cam.roll,clamp(-lat*.5,-.08,.08),1-Math.pow(.05,dt));
    camera.position.copy(P);cam.look.copy(Q);camera.up.copy(UP);camera.lookAt(Q);camera.rotateZ(cam.roll)}
  const fk=1-Math.pow(.01,dt);if(Math.abs(camera.fov-cam.fovT)>.01){camera.fov=lerp(camera.fov,cam.fovT,fk);camera.updateProjectionMatrix()}
}

// ═══════════════════════════════════════════════════════════════════════════
// 10. HUD: scramble text (XurOrb), leader-line annotations (video 2), lenses
// ═══════════════════════════════════════════════════════════════════════════
const CHARS='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←';
function scramble(el,text,frames=22){const len=text.length;let f=0;clearInterval(el._sc);el._final=text;
  if(REDUCED){el.textContent=text;return}
  el._sc=setInterval(()=>{f++;let o='';for(let i=0;i<len;i++)o+=f/frames>i/len||text[i]===' '?text[i]:CHARS[Math.floor(Math.random()*CHARS.length)];
    el.textContent=o;if(f>=frames){clearInterval(el._sc);el.textContent=text}},30)}
const $=id=>document.getElementById(id);
const svg=$('leaders'),labelsEl=$('labels'),annosEl=$('annos');
function project(v){const p=v.clone().project(camera);return {x:(p.x*.5+.5)*innerWidth,y:(-p.y*.5+.5)*innerHeight,front:p.z<1&&p.z>-1}}
const slots={};
function anno(name){if(slots[name])return slots[name];const el=document.createElement('div');el.className='anno';annosEl.appendChild(el);
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');svg.appendChild(path);
  // the pointer on the card keeps it (UX-PLAN 13: moving onto its paths never loses it); leaving it lets it go
  el.addEventListener('mouseenter',()=>{const s=slots[name];s.over=true;if(s.lingerT){clearTimeout(s.lingerT);s.lingerT=null}});
  el.addEventListener('mouseleave',()=>{const s=slots[name];s.over=false;if(name==='hover')lingerClear(name)});
  return slots[name]={el,path,anchor:null,on:false,key:null}}
// HOVER TIMING (UX-PLAN 13): a hover card appears once the pointer has rested HOVER_INTENT_MS on a thing (a sweep across
// the scene shows nothing), swaps at once while one is showing, and lingers CARD_LINGER_MS after the pointer leaves.
const HOVER_INTENT_MS=80,CARD_LINGER_MS=250;
function lingerClear(name){const s=slots[name];if(!s)return;if(s.pend){clearTimeout(s.intentT);s.intentT=null;s.pend=null}
  if(!s.on||s.lingerT||s.over)return;s.lingerT=setTimeout(()=>{s.lingerT=null;if(!s.over)clearAnno(name)},CARD_LINGER_MS)}
// cell=true: the point itself swells into an organic cell with the text INSIDE (like an artifact
// cell on hover), centred on the anchor and grown from it; otherwise a leader-line label.
const lmCell=k=>({cell:true,col:CELL_COL[lmBest[k]]||'#7fe8ff'});
function setAnno(name,key,anchorFn,html,o={}){const s=anno(name);if(s.lingerT){clearTimeout(s.lingerT);s.lingerT=null}
  if(name==='hover'&&!s.on){   // nothing showing yet: wait for the pointer to rest on this thing
    if(s.pend?.key!==key){clearTimeout(s.intentT);s.intentT=setTimeout(()=>{s.intentT=null;const p=s.pend;s.pend=null;if(p)showAnno(...p)},HOVER_INTENT_MS)}
    s.pend=Object.assign([name,key,anchorFn,html,o],{key});return}
  showAnno(name,key,anchorFn,html,o)}
function showAnno(name,key,anchorFn,html,{hot=false,cell=false,col=null}={}){const s=anno(name);
  if(s.cell!==cell){s.cell=cell;s.el.classList.toggle('cell',cell);s.key=null}
  if(col)s.el.style.setProperty('--cell',col);
  if(s.key!==key){s.el.innerHTML=html;s.key=key;const t=s.el.querySelector('.t');if(t)scramble(t,t.textContent,18);
    if(cell){s.el.classList.remove('on');void s.el.offsetWidth}} // a new cell grows again from its own point
  s.anchor=anchorFn;s.on=true;s.el.classList.add('on');s.path.classList.toggle('hot',hot)}
function clearAnno(name){const s=slots[name];if(!s)return;clearTimeout(s.intentT);clearTimeout(s.lingerT);s.intentT=s.lingerT=null;s.pend=null;
  s.on=false;s.key=null;s.el.classList.remove('on');s.path.setAttribute('d','')}
function placeAnnos(){
  for(const s of Object.values(slots)){if(!s.on||!s.anchor){continue}
    const a=s.anchor();if(!a||!a.front){s.el.style.opacity=0;s.path.setAttribute('d','');continue}s.el.style.opacity='';
    const w=s.el.offsetWidth,h=s.el.offsetHeight;
    if(s.cell){ // centred on the point it grew from; the transform origin tracks the point when clamped
      const left=clamp(a.x-w/2,12,innerWidth-w-12),top=clamp(a.y-h/2,60,innerHeight-h-60);
      s.el.style.left=left+'px';s.el.style.top=top+'px';s.el.style.transformOrigin=`${a.x-left}px ${a.y-top}px`;
      s.path.setAttribute('d','');s.el.classList.remove('left','right');continue}
    const right=a.x<innerWidth*.62;const dx=right?1:-1;const ex=a.x+dx*38,ey=a.y-30,tx=ex+dx*46;
    const fits=right?tx+8+w<innerWidth-12:tx-8-w>12;
    if(fits){
      s.path.setAttribute('d',`M${a.x},${a.y}L${ex},${ey}L${tx},${ey}`);
      const left=right?tx+8:tx-8-w,top=clamp(ey-14,60,innerHeight-h-70);
      s.el.style.left=left+'px';s.el.style.top=top+'px';s.el.classList.toggle('left',!right);s.el.classList.toggle('right',right)}
    else{ // narrow window: the text hangs below (or above) its anchor and never covers it
      const below=a.y<innerHeight*.55,vy=below?a.y+44:a.y-44;
      s.path.setAttribute('d',`M${a.x},${a.y}L${a.x},${vy}`);
      s.el.style.left=clamp(a.x-w/2,12,innerWidth-w-12)+'px';s.el.style.top=clamp(below?vy+6:vy-6-h,60,innerHeight-h-70)+'px';
      s.el.classList.remove('left');s.el.classList.add('right')}}}
// family region labels around the skin
const regLabelEls=REG.map((d,i)=>{const el=document.createElement('div');el.className='rlabel';
  const lms=M.landmarks.filter(l=>l.domain===d),pv=lms.filter(l=>l.tier!=='candidate').length;
  const fresh=lms.filter(l=>l.born&&nowS()-l.born<7*86400).length,against=lms.filter(l=>l.contradictions>0).length;   // UX-PLAN 7.1
  const top=lms.slice().sort((a,b)=>(b.activations||0)-(a.activations||0)).slice(0,2).map(l=>l.claim.length>48?l.claim.slice(0,47)+'…':l.claim);
  el.innerHTML=`<b style="color:${domCol(d)}">${esc(domWord(d))}</b>${fmt(M.domCounts[d]||0)} moments ${regN[i]?syncHTML(regSync[i])+` <span class="syncr">${pv} of ${regN[i]} claims proven</span>`:'<span class="syncr">no claims yet</span>'}${fresh||against?`<i>${fresh?`+${fmt(fresh)} new this week`:''}${fresh&&against?' · ':''}${against?`<span class="w">${fmt(against)} contradicted</span>`:''}</i>`:''}${top.map(c=>`<i class="knows">knows: ${esc(c)}</i>`).join('')}${(domTop[i]||[]).map(x=>`<i>${esc(x)}</i>`).join('')}`;labelsEl.appendChild(el);
  const p=document.createElementNS('http://www.w3.org/2000/svg','path');svg.appendChild(p);return {el,p}});
// the coordinate spaces as layers: press s and each shell names itself, with who may write there
const spaceLabelEls=SPACES.map((s,i)=>{const el=document.createElement('div');el.className='rlabel';
  el.innerHTML=`<b style="color:${chanTint(s.write_lock)}">${esc(SPACE_WORD[s.id]||String(s.id).replace(/_/g,' '))}</b>${s.write_lock!=null?`<i>${esc(LOCK_WORD[s.write_lock]||'')}</i>`:''}`;labelsEl.appendChild(el);
  const p=document.createElementNS('http://www.w3.org/2000/svg','path');svg.appendChild(p);return {el,p}});
function placeSpaceLabels(show){
  const c=project(new V3()),e=project(new V3(R,0,0).applyQuaternion(camera.quaternion)),rs=Math.abs(e.x-c.x)||200;
  const right=new V3(1,0,0).applyQuaternion(camera.quaternion),up=new V3(0,1,0).applyQuaternion(camera.quaternion);
  spaceLabelEls.forEach((L,i)=>{if(!show){L.el.style.opacity=0;L.p.setAttribute('d','');return}
    const a=-.6+i*.19,pt=project(right.clone().multiplyScalar(Math.cos(a)*spR[i]).addScaledVector(up,Math.sin(a)*spR[i]));
    const lx=c.x+rs+50,ly=c.y-130+i*40;L.el.style.opacity=.85;L.el.style.left=(lx+6)+'px';L.el.style.top=(ly-8)+'px';L.el.style.textAlign='left';
    L.p.setAttribute('d',`M${pt.x},${pt.y}L${lx},${ly}`)})}
// THE JOBS (UX-PLAN 9.2): each job's name on the outer ring, over the sectors of its consumers
const JOBS=[];ORC.forEach((o,i)=>{const j=o.job||'';if(!j)return;const last=JOBS[JOBS.length-1];if(last&&last.job===j)last.to=i;else JOBS.push({job:j,from:i,to:i})});
const jobLabelEls=JOBS.map(g=>{const el=document.createElement('div');el.className='rlabel job';el.textContent=g.job.replace(/_/g,' ');labelsEl.appendChild(el);return el});
function placeJobLabels(show){JOBS.forEach((g,i)=>{const el=jobLabelEls[i];if(!show){el.style.opacity=0;return}
  const th=((g.from+g.to+1)/2)/NSEC*Math.PI*2+Math.PI/2,a=project(new V3(Math.cos(th)*R*1.16,Math.sin(th)*R*1.16,0));
  el.style.opacity=.7;el.style.left=(a.x-el.offsetWidth/2)+'px';el.style.top=(a.y-6)+'px'})}
// A LIVE DECISION (UX-PLAN 9.1): a ray from its consumer's sector into the pupil and, for a moment, the probability of
// each offered option as arcs around the pupil's rim (arc length = probability, the chosen one bright). It returns
// bright when the Oracle acted; when it only watched, the ray fades.
const liveSvg=document.createElementNS('http://www.w3.org/2000/svg','svg');liveSvg.id='orclive';$('hud').appendChild(liveSvg);
const liveLine=document.createElement('div');liveLine.id='orcline';$('hud').appendChild(liveLine);
function drawLiveDecision(){const d=state.lastDecision,age=d?clock.elapsedTime-d.t:9;
  if(state.lens!=='oracle'||cam.mode!=='orbit'||!d||d.t==null||age>4){if(liveSvg.childNodes.length)liveSvg.innerHTML='';liveLine.style.opacity=0;return}
  const c=project(new V3()),rim=Math.hypot(project(new V3(R*.4,0,0)).x-c.x,project(new V3(R*.4,0,0)).y-c.y);   // outside the opened pupil
  const th=(d.sec+.5)/NSEC*Math.PI*2+Math.PI/2,s0=project(new V3(Math.cos(th)*R,Math.sin(th)*R,0)),fade=Math.max(0,1-age/1.6);
  const ex=c.x+(s0.x-c.x)*rim/Math.max(1,Math.hypot(s0.x-c.x,s0.y-c.y)),ey=c.y+(s0.y-c.y)*rim/Math.max(1,Math.hypot(s0.x-c.x,s0.y-c.y));
  const k=Math.min(1,age/.25);   // the ray travels in, then (acted) the light comes back out
  let h=`<path d="M${s0.x.toFixed(1)},${s0.y.toFixed(1)}L${(s0.x+(ex-s0.x)*k).toFixed(1)},${(s0.y+(ey-s0.y)*k).toFixed(1)}" class="ray${d.acted?' acted':''}" style="opacity:${(d.acted?1:.55)*fade}"/>`;
  liveSvg.innerHTML=age<=1.6?h:'';
  // the line under the ring: what decided, how sure, whether it acted, its top options (stays a little longer)
  const key=d.o.consumer+d.t;if(liveLine.dataset.k!==key){liveLine.dataset.k=key;
    liveLine.innerHTML=`${esc(oracleWord(d.o.consumer))} · <em>${Math.round(d.conf*100)}%</em> sure · ${d.acted?'<span class="u">it acted</span>':'it watched'}${(d.options||[]).length?'<br>'+d.options.slice(0,3).map(o=>`${esc(String(o.name).replace(/_/g,' '))} ${Math.round((+o.p||0)*100)}%`).join(' · '):''}`}
  liveLine.style.left=c.x+'px';liveLine.style.top=(c.y+rim+22)+'px';liveLine.style.opacity=Math.max(0,Math.min(1,(4-age)/1.2))}
// INSIDE A TERRITORY (UX-PLAN 7.2): its sub-sectors are named where they sit, and the 5 claims nearest the camera
// carry their words - labels by distance, so the inside reads without hovering every crystal.
const subEls=SUB.map(sb=>{const el=document.createElement('div');el.className='rlabel sub';el.textContent=sb.label+(sb.status==='candidate'?' (still forming)':'');labelsEl.appendChild(el);return el});
const nearEls=[0,1,2,3,4].map(()=>{const el=document.createElement('div');el.className='rlabel near';labelsEl.appendChild(el);return el});
function placeInsideLabels(show){const ri=state.diveReg;
  SUB.forEach((sb,j)=>{const el=subEls[j];if(!show||sb.ri!==ri){el.style.opacity=0;return}
    const a=project(subC[j].clone().multiplyScalar(R*.9));if(!a.front){el.style.opacity=0;return}
    el.style.opacity=.6;el.style.left=(a.x-el.offsetWidth/2)+'px';el.style.top=(a.y-7)+'px'});
  const near=show?LM.map((l,k)=>({k,d:somaPos[k].distanceTo(camera.position)})).filter(o=>LM[o.k].dom===ri&&somaData[o.k*8+3]>0&&o.k!==state.focusSoma&&o.k!==state.hoverSoma)
    .sort((a,b)=>a.d-b.d).slice(0,5):[];
  nearEls.forEach((el,i)=>{const o=near[i];if(!o){el.style.opacity=0;return}const a=project(somaWorld(o.k));if(!a.front){el.style.opacity=0;return}
    const t=LM[o.k].claim;if(el.dataset.k!==String(o.k)){el.dataset.k=o.k;el.textContent=t.length>40?t.slice(0,39)+'…':t}
    el.style.opacity=clamp(1.2-o.d/(R*.9),.25,.8);el.style.left=(a.x+10)+'px';el.style.top=(a.y-6)+'px'})}
function placeRegionLabels(show){
  const c=project(new V3()),edge=project(new V3(R,0,0).applyQuaternion(camera.quaternion));const rs=Math.abs(edge.x-c.x)||200;
  regC.forEach((v,i)=>{const L=regLabelEls[i];const camDir=camera.position.clone().normalize();const vis=show&&v.dot(camDir)>.15;
    if(!vis){L.el.style.opacity=0;L.p.setAttribute('d','');return}
    const a=project(v.clone().multiplyScalar(R));const side=a.x<c.x?-1:1;const lx=c.x+side*(rs+60),ly=a.y;
    L.el.style.opacity=state.hoverReg===i?1:(state.hoverReg>=0?.35:.75);L.el.classList.toggle('hot',state.hoverReg===i);
    const w=L.el.offsetWidth;const left=clamp(side>0?lx+6:lx-6-w,8,innerWidth-w-8);
    L.el.style.left=left+'px';L.el.style.top=(ly-8)+'px';L.el.style.textAlign=side>0?'left':'right';
    L.p.setAttribute('d',`M${a.x},${a.y}L${side>0?Math.min(lx,left-6):Math.max(lx,left+w+6)},${ly}`);L.p.classList.toggle('hot',state.hoverReg===i)})}
const LENSES=[['cortex','cortex'],['timeline','timeline'],['artifacts','artifacts'],['oracle','oracle']];
LENSES.forEach(([k,w],i)=>{const a=document.createElement('a');a.dataset.l=k;a.textContent=w;a.onclick=()=>setLens(k);
  a.onmouseenter=()=>scramble(a,w,14);$('lenses').appendChild(a)});
function hint(t){$('hint').innerHTML=t}
// THE KEY: the five shapes of memory, drawn the way the scene draws them; click one to see only that kind
const KEY=[['claim','a claim, proven'],['learning','a claim, still learning'],['pin','a pin, held on purpose'],['moment','a moment, as it happens'],['node','a node in a layer']];
function keyIcon(kind){const c=document.createElement('canvas');c.width=c.height=44;const g=c.getContext('2d');g.translate(22,22);
  const hex=(r,rot=0)=>{g.beginPath();for(let k=0;k<6;k++){const a=k/6*Math.PI*2+rot;g[k?'lineTo':'moveTo'](Math.cos(a)*r,Math.sin(a)*r)}g.closePath()};
  g.lineWidth=1.6;
  if(kind==='claim'||kind==='learning'){const cols=['#ffffff','#5dffb0','#5dffb0','#7fe8ff','#7fe8ff','#8aa3b0'];
    if(kind==='claim')for(let k=0;k<6;k++){const a0=k/6*Math.PI*2,a1=(k+1)/6*Math.PI*2;g.beginPath();g.moveTo(0,0);g.lineTo(Math.cos(a0)*13,Math.sin(a0)*13);g.lineTo(Math.cos(a1)*13,Math.sin(a1)*13);
      g.closePath();g.globalAlpha=.28+.2*Math.cos(k-2.4);g.fillStyle=cols[k];g.fill()}
    g.globalAlpha=kind==='claim'?.95:.6;g.strokeStyle='#cfe7f2';hex(13);g.stroke();if(kind==='claim'){g.globalAlpha=.9;g.fillStyle='#fff';g.beginPath();g.arc(0,0,2.6,0,7);g.fill()}}
  else if(kind==='pin'){g.globalAlpha=.55;g.fillStyle='#ffcf6b';hex(6.5,Math.PI/6);g.fill();g.globalAlpha=.95;g.strokeStyle='#ffe6b0';
    for(const sx of [-1,1]){g.beginPath();g.moveTo(sx*13,-11);g.lineTo(sx*16,-11);g.lineTo(sx*16,11);g.lineTo(sx*13,11);g.stroke()}}
  else if(kind==='moment'){const gr=g.createLinearGradient(-16,8,12,-6);gr.addColorStop(0,'rgba(127,232,255,0)');gr.addColorStop(1,'rgba(214,246,255,.95)');
    g.strokeStyle=gr;g.lineWidth=2;g.beginPath();g.moveTo(-16,8);g.lineTo(11,-5);g.stroke();g.fillStyle='#fff';g.beginPath();g.arc(11,-5,2.4,0,7);g.fill()}
  else{g.globalAlpha=.85;g.strokeStyle='#9fd0e6';g.beginPath();g.arc(0,0,6,0,7);g.stroke();g.fillStyle='#cfe7f2';g.beginPath();g.arc(0,0,1.8,0,7);g.fill()}
  return c}
let keyFocus=null;
function setKindFocus(k){keyFocus=k;const kind=k==='learning'?'claim':k;
  for(const [kk,objs] of Object.entries(KIND_OBJ))for(const o of objs)o.visible=!kind||kk===kind;
  // the rest of the organism steps back while one kind is singled out
  mist.visible=moteObj.visible=!kind;skinMat.uniforms.uSkin.value=kind?.3:1;
  // a claim still learning vs proven: the glyph layer shows only that tier
  somaCellMat.uniforms.uTier.value=k==='claim'?1:k==='learning'?0:-1;
  $('key').classList.toggle('iso',!!k);document.querySelectorAll('#key a').forEach(a=>a.classList.toggle('on',a.dataset.k===k))}
const KEY_COUNT={claim:LM.filter(l=>l.tier!=='candidate').length,learning:LM.filter(l=>l.tier==='candidate').length,pin:PINS.length,
  moment:M.meta?.counts?.events||M.events.length,node:NDS.length};
KEY.forEach(([k,w])=>{const a=document.createElement('a');a.dataset.k=k;
  a.append(Object.assign(document.createElement('span'),{textContent:w}),Object.assign(document.createElement('em'),{className:'kn',textContent:fmt(KEY_COUNT[k]||0)}),keyIcon(k));
  a.onclick=()=>setKindFocus(keyFocus===k?null:k);$('key').appendChild(a)});
// THE CONTROL SHEET (UX-PLAN 3.3): `?` (or "? keys" at the foot of the key) lists the gestures of the view you are in.
// Only bindings that exist (the keydown handler, click(), the wheel): a sheet that promises a key is worse than none.
const HELP={
  cortex:[['hover','name a territory, a claim, a pin'],['click','dive into a territory · focus a claim'],['Enter','go in where the pointer is'],
    ['Esc · Alt+← · back','one level out'],['k','health view (Kyudo)'],['s','show the spaces'],['wheel','nearer · further']],
  timeline:[['hover a bead','its strand and what memory gave it'],['← →','strand to strand in time'],['↑ ↓ · wheel','move through time'],
    ['click a bead','its recall arches'],['Enter','walk into the strand'],['Ctrl + wheel','zoom in to the turns'],['g','watch it grow'],['Esc','clear the focus']],
  corridor:[['↑ ↓ · wheel','walk along the strand'],['← →','claim to claim'],['Shift + ← →','turn to turn'],['Tab','walk to the far doorway'],
    ['click a claim','the thread it belongs to'],['Enter','that claim in the cortex'],['the far door','walk into the next strand'],['Esc','back to the helix']],
  artifacts:[['click','open a folder · a thing'],['Esc','up one folder']],
  oracle:[['hover a sector','a consumer and its job'],['click','its ladder, history and curve'],['Esc','back to the ring']]};
const HELP_ALL=[['1 – 4','cortex · timeline · artifacts · oracle'],['/','search what IRIS remembers'],['f','follow IRIS live'],['r','replay the last turn'],['?','this sheet']];
const help={on:false,view:''};
const helpView=()=>cam.mode==='tunnel'?'corridor':state.lens;
function renderHelp(){help.view=helpView();const rows=[...(HELP[help.view]||[]),...HELP_ALL];
  $('help').innerHTML=`<h4><span>keys · ${esc(help.view)}</span><a data-helpx>close ✕</a></h4>`+rows.map(([k,w])=>`<div class="row"><b>${esc(k)}</b><span>${esc(w)}</span></div>`).join('')}
function toggleHelp(on=!help.on){help.on=on;if(on)renderHelp();$('help').classList.toggle('on',on)}
$('help').addEventListener('click',e=>{if(e.target.closest('[data-helpx]'))toggleHelp(false)});
{const q=document.createElement('a');q.className='helpk';q.textContent='? keys';q.title='the keys of this view';q.onclick=()=>toggleHelp();$('key').appendChild(q)}
// FIRST-OPEN COACH MARKS (UX-PLAN 3.3): the three gestures, once per viewer; any gesture or ✕ dismisses them.
const COACH_KEY='iris.memory.coach.v1';
function coachSeen(){try{return localStorage.getItem(COACH_KEY)==='1'}catch{return true}}
function dismissCoach(){const c=$('coach');if(!c.classList.contains('on'))return;c.classList.remove('on');try{localStorage.setItem(COACH_KEY,'1')}catch{}}
if(!coachSeen()){$('coach').innerHTML='<span><b>hover</b>look</span><span><b>click</b>focus</span><span><b>Esc</b>back</span><span><b>?</b>all keys</span><a data-coachx>✕</a>';
  setTimeout(()=>$('coach').classList.add('on'),1600);setTimeout(dismissCoach,16000);
  $('coach').addEventListener('click',e=>{if(e.target.closest('[data-coachx]'))dismissCoach()})}
const rail={el:$('rail'),svg:$('rail').querySelector('svg'),lbl:$('rail').querySelector('.rl'),marks:[],pos:null,
  build(T){const NS='http://www.w3.org/2000/svg',svg=this.svg;svg.innerHTML='';this.marks=[];this.el.classList.toggle('on',!!T);if(!T)return;
    const W=svg.clientWidth||600,X=u=>8+u*(W-16),mk=(tag,at)=>{const e=document.createElementNS(NS,tag);for(const k in at)e.setAttribute(k,at[k]);svg.appendChild(e);return e};
    mk('line',{x1:8,y1:14,x2:W-8,y2:14,stroke:'rgba(212,236,246,.22)'});
    T.items.forEach(it=>{if(it.type==='msg')mk('line',{x1:X(it.u),y1:9,x2:X(it.u),y2:12,stroke:it.m.role==='user'?'#ffe8fb':'#ff5fd6','stroke-opacity':.6})});
    T.gates.forEach(gt=>{const c=gt.ep.corrected?'#fff':gt.ep.outcome==='failure'?'#ff4a3d':gt.ep.outcome==='partial'?'#ffb547':'#7fe8ff';
      const r=mk('rect',{x:X(gt.u)-1.5,y:6,width:3,height:16,fill:c,'fill-opacity':.7});r.onclick=()=>{cam.tpT=Math.max(0,gt.u-.02);cam.idle=-9};
      r.onmouseenter=()=>this.lbl.textContent='task · '+gt.ep.summary});
    T.pins.forEach(b=>{const x=X(b.u),c=pinType(b.p.type).col;
      const e=mk('path',{d:`M${x},9 L${x+3.5},14 L${x},19 L${x-3.5},14 Z`,fill:c,'fill-opacity':b.p.held?.95:.6});e.onclick=()=>{cam.tpT=Math.max(0,b.u-.02);cam.idle=-9};
      e.onmouseenter=()=>this.lbl.textContent='pin · '+b.p.title});
    T.stars.forEach((st,i)=>{const c=CELL_COL[lmBest[st.li]]||'#8aa3b0';
      const e=mk('circle',{cx:X(st.u),cy:14,r:4.2,fill:'#020306',stroke:c,'stroke-width':1.4});e.onclick=()=>{cam.tpT=Math.max(0,st.u-.02);cam.idle=-9};
      e.onmouseenter=()=>this.lbl.textContent=LM[st.li].claim;this.marks.push({e,st})});
    const endM=mk('circle',{cx:W-8,cy:14,r:6,fill:'rgba(2,3,6,.6)',stroke:'#7fe8ff','stroke-dasharray':'2 2','pointer-events':'all'});
    endM.onclick=()=>{cam.tpT=.95;cam.idle=-9};endM.onmouseenter=()=>this.lbl.textContent='the doorway: the next thread, or back to the beginning';
    this.pos=mk('path',{d:'M0,0',fill:'#f4fbff'});this.W=W;this.lbl.textContent=T.session.objective},
  update(tp){if(!this.pos||!tunnel)return;const x=8+clamp(tp+.02,0,1)*(this.W-16);this.pos.setAttribute('d',`M${x-4},29 L${x+4},29 L${x},23 Z`);
    for(const m of this.marks){const on=tunnel.sel<0||m.st.li===tunnel.sel||tunnel.linked.has(tunnel.sel+'-'+m.st.li)||tunnel.linked.has(m.st.li+'-'+tunnel.sel);
      m.e.setAttribute('opacity',on?1:.25)}}};
// where you are, as a path: memory > the view > the territory or session you are in > the claim you hold
// FOLLOW (owner: on by default, a toggle turns it off) - its state; the tap itself is in section 12. unseen = live
// moments that arrived while the time cursor was in the past (edge case 22: nothing moves, the "now" chip counts them).
const follow={on:true,q:[],next:0,missed:0,unseen:0};
// MEMORY -> CHAT (MEMORY-UX-PLAN 4.6): the turn a chat link came from (focus "turn:<conv>:<turn>"), so the corridor's
// breadcrumb leads back to it; any corridor of a chat strand offers "continue in chat".
let chatTurn=null;
try{follow.on=localStorage.getItem('iris.memory.follow')!=='0'}catch(e){}
let crumbKey='';
function updateCrumb(){if(help.on&&help.view!==helpView())renderHelp();   // the sheet follows the view
  const parts=['memory'];
  if(cam.mode==='tunnel'&&tunnel){parts.push('timeline','strand · '+tunnel.session.objective);if(tunnel.sel>=0&&LM[tunnel.sel])parts.push('claim · '+LM[tunnel.sel].claim)}
  else{const lw={cortex:'cortex',timeline:'timeline',artifacts:'artifacts',oracle:'oracle'}[state.lens];if(lw)parts.push(lw);
    if(state.inside&&state.diveReg>=0)parts.push('territory · '+domWord(REG[state.diveReg]));
    if(state.inside&&state.focusSoma>=0&&LM[state.focusSoma])parts.push('claim · '+LM[state.focusSoma].claim);
    if(state.lens==='timeline'&&sync.sid)parts.push('strand · '+titleOf(sync.sid))}
  const when=cursorNow()?'':new Date(cursorTs()*1000).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
  const s_=cam.mode==='tunnel'&&tunnel?tunnel.session:null,inChat=!!s_&&!!(s_.messages||[]).length;
  const back=inChat&&chatTurn&&chatTurn.conv===s_.id?chatTurn.turn:'';
  const working=performance.now()-liveAt<LIVE_DOT_S*1000;
  const k=parts.join('|')+'|'+when+'|'+follow.unseen+'|'+(inChat?s_.id:'')+'|'+back+'|'+working;if(k===crumbKey)return;crumbKey=k;
  $('crumb').innerHTML=(working?'<span class="livedot" title="IRIS is working on a turn now"></span>':'')+
    parts.map((p,i)=>i===parts.length-1?`<b>${esc(p)}</b>`:esc(p)).join('<i>›</i>')+
    (inChat?`<a class="chat" data-conv="${esc(s_.id)}" data-turn="${esc(back)}" title="open this conversation in the chat">${back?'↩ back to the turn in chat':'↗ continue in chat'}</a>`:'')+
    ((inChat||s_?.ghost)&&opts.correctTarget?`<a class="strandact" data-sact="forget" data-sid="${esc(s_.id)}">forget what IRIS learned here</a><a class="strandact" data-sact="purge" data-sid="${esc(s_.id)}">purge its words</a>`:'')+
    (uses.k>=0&&state.lens==='timeline'?`<a class="when">uses of claim · ${fmt(uses.n)} turn${uses.n===1?'':'s'}</a>`+
      (uses.chat?`<a class="chat" data-conv="${esc(uses.chat.conv)}" data-turn="${esc(uses.chat.turn)}" title="open the newest turn that was given this claim">↗ newest use in chat</a>`:''):'')+
    (when?`<a class="when${follow.unseen?' pulse':''}" title="return to now">as of ${esc(when)} · now ↻${follow.unseen?` · ${fmt(follow.unseen)} new`:''}</a>`:'')}
$('crumb').addEventListener('click',e=>{if(e.target.closest('.when')){state.replay=false;state.scrubT=1;follow.unseen=0}
  const sa=e.target.closest('[data-sact]');if(sa){strandAction(sa.dataset.sact,sa.dataset.sid,sa);return}
  const c=e.target.closest('.chat');if(c)window.dispatchEvent(new CustomEvent('iris:open_conversation',{detail:{conversationId:c.dataset.conv,turnId:c.dataset.turn||undefined}}))});
function updateStats(fps){const c=M.meta.counts||{};
  $('stats').innerHTML=`<em>${fmt(c.landmarks||NL)}</em> claims · <em>${fmt(c.events||M.events.length)}</em> moments · <em>${fmt(c.sessions||sess.length)}</em> strands<br>`+
  `<em>${fmt(c.fragments||0)}</em> fragments · <em>${fmt(c.artifacts||M.artifacts.length)}</em> things made`+
  `${PINS.length||NDS.length?` · <em>${PINS.length}</em> pins · <em>${NDS.length}</em> nodes in <em>${SPACES.length}</em> layers`:''}<br>`+
  `${Math.round(fps)} fps · ${fmt(NS+NI+mistN+(tunnel?26000:0))} points · ${esc(M.meta.source)}`}
const tickLines=document.querySelectorAll('#ticker .line');
// the immune response in the ticker: what the guard noticed, where, and whether it counted
function tickGuard(q,ri){const col=q.shadow?'#7d8f9b':q.signal==='quorum_reorganization_reset'?'#9fd8c8':'#ffb547';
  tickLines[0].innerHTML=tickLines[1].innerHTML;
  tickLines[1].innerHTML=`<span class="dot" style="background:${col}"></span><span class="tx"></span><span style="color:var(--faint)"> · guard${q.shadow?' · measured, not counted':''}${ri>=0?' · '+esc(domWord(REG[ri])):''}</span>`;
  const tx=tickLines[1].querySelector('.tx');tx.style.color='rgba(212,236,246,.55)';
  scramble(tx,(QUORUM_WORD[q.signal]||String(q.signal).replace(/_/g,' '))+' · '+ago(q.ts),16)}
function tick(e){const col=FAM[FAMI[e.family]]?.color||'#fff';const strong=e.evidence==='user';
  {const o=tickLines[1].querySelector('.tx');if(o&&o._sc){clearInterval(o._sc);if(o._final!=null)o.textContent=o._final}}   // finish its letters first
  tickLines[0].innerHTML=tickLines[1].innerHTML;
  tickLines[1].innerHTML=`<span class="dot" style="background:${e.valence==='sets_back'?'#ff4a3d':col};box-shadow:0 0 8px ${col}"></span><span class="tx"></span><span style="color:var(--faint)"> · ${FAM[FAMI[e.family]]?.word||'other'}${e._past&&e.ts?' · '+ago(e.ts):''}</span>`;
  const tx=tickLines[1].querySelector('.tx');tx.style.color=strong?'#fff':`rgba(212,236,246,${.35+(EVID[e.evidence]??.2)*.65})`;tx.style.fontWeight=strong?600:400;scramble(tx,readEvent(e),16)}

// ═══════════════════════════════════════════════════════════════════════════
// 11. state, lenses, transitions
// ═══════════════════════════════════════════════════════════════════════════
const state={showSpaces:false,lens:'cortex',inside:false,diving:false,diveReg:-1,hoverReg:-1,hoverSoma:-1,focusSec:-1,focusSoma:-1,hoverBead:-1,hoverSec:-1,
  hoverNode:-1,morph:{h:0,i:0,c:0},morphT:{h:0,i:0,c:0},vis:{forest:1,wire:1,xur:1,beads:0,rings:.7,core:1},visT:{forest:1,wire:1,xur:1,beads:0,rings:.7,core:1},
  scrub:1,scrubT:1,replay:false,search:'',pupil:1,lastDecision:null,from:'cortex'};
// the time cursor (see "THE TIME CURSOR" below)
const cursorTs=()=>T0+(nowS()-T0)*state.scrub, cursorNow=()=>state.scrubT>.995;
const SCRUB_LENS=new Set(['cortex','timeline','artifacts']);
let scrubSeen=1;   // the cursor value the helix last centred on (only a cursor MOVE moves the helix; the wheel stays free)
function setLens(l){
  if(state.diving)return;
  if(cam.mode==='tunnel'){exitTunnel(()=>setLens(l));return}
  if(state.inside){exitInterior(()=>setLens(l));return}
  state.lens=l;state.focusSec=-1;if(l!=='cortex'&&state.health)setHealth(false);if(l!=='cortex'&&keyFocus)setKindFocus(null);clearAnno('focus');clearAnno('hover');state.focusSoma=-1;setFocusSoma(-1);tissue.focus=-1;
  document.querySelectorAll('#lenses a').forEach(a=>{a.classList.toggle('on',a.dataset.l===l)});
  const m=state.morphT,v=state.visT;
  const hx=l==='timeline';m.h=hx?1:0;m.i=l==='oracle'?1:0;m.c=l==='artifacts'?1:0;
  Object.assign(v,{forest:l==='cortex'?1:l==='artifacts'?.9:l==='timeline'?.12:0,wire:l==='cortex'||l==='artifacts'?1:0,xur:hx||l==='oracle'?0:1,   // the Oracle has its own centre: the pupil (owner, 2026-10-25)
    
    beads:l==='timeline'?1:0,rings:l==='cortex'?.7:l==='artifacts'?.35:0,core:hx?.12:1});
  tissue.on=l==='artifacts';tcv.classList.toggle('on',tissue.on);if(tissue.on){layoutTissue(true);tissue.t=Math.min(tissue.t,.05)}
  $('scrub').classList.toggle('on',SCRUB_LENS.has(l));
  const T=$('title');T.style.opacity=0;
  cam.mode='orbit';
  if(l==='cortex'){cam.targetT.set(0,0,0);cam.distT=58;cam.elT=.16}
  if(l==='timeline'){cam.targetT.set(0,0,0);cam.distT=66;cam.elT=.05}
  if(l==='oracle'){cam.targetT.set(0,0,0);cam.distT=44;cam.azT=Math.round(cam.az/(Math.PI*2))*Math.PI*2;cam.elT=0}
  if(l==='artifacts'){cam.targetT.set(-1.0*R,0,0);cam.distT=62;cam.azT=Math.round(cam.az/(Math.PI*2))*Math.PI*2;cam.elT=0;setTimeout(()=>layoutTissue(false),900)}
  hint({cortex:'drag · turn the mind &nbsp; click a region · go inside<br>/ · search &nbsp; g · watch it grow &nbsp; s · coordinate layers &nbsp; t · theme',
    timeline:'scroll · move through time &nbsp; ctrl + scroll · zoom into the turns &nbsp; hover a strand · what the memory gave it<br>hover its strands · read a recall &nbsp; click · step inside',
    artifacts:'hover · a cell swells &nbsp; click · open it',
    oracle:'hover a sector · what IRIS is learning to decide'}[l]);
}
function regionWorld(i,s=R){return regC[i].clone().multiplyScalar(s)}
function dive(i){
  if(state.diving||state.inside)return;state.diving=true;state.diveReg=i;clearAnno('hover');
  const c=regC[i].clone(),lookIn=c.clone().multiplyScalar(-R*.25);
  // one flight: swing round to the region, the cells open as we near, pass through, settle inside
  const pts=[camera.position.clone(),...arcTo(camera.position,c,R*2.0,3),c.clone().multiplyScalar(R*1.08),c.clone().multiplyScalar(R*.6)];
  const looks=[cam.look.clone(),new V3(),new V3(),lookIn.clone().multiplyScalar(.3),lookIn];
  LM.forEach((l,k)=>{somaData[k*8+6]=l.dom===i?1:0});somaTex.needsUpdate=true;
  tweenPath(pts,looks,64,REDUCED?.01:2.8,{kick:9,
    onT:e=>{if(e>.42)state.openT=1;if(e>.6)state.focusDimT=1},
    done:()=>{cam.mode='fly';flyFrom(camera.position,lookIn);cam.fovT=64;state.inside=true;state.diving=false;
      hint('drag · look &nbsp; scroll / w a s d · swim &nbsp; q e · down up<br>click a thought · go to it &nbsp; click space · glide there &nbsp; esc · back out');
      const T=$('title');T.innerHTML=`${esc(domWord(REG[i]))}<small>the thoughts of this territory · ${fmt(M.domCounts[REG[i]]||0)} moments</small>`;T.style.opacity=1}});
}
function exitInterior(done){
  if(!state.inside)return done&&done();
  const i=state.diveReg,c=regC[i];clearAnno('focus');clearAnno('hover');setFocusSoma(-1);state.focusDimT=0;
  LM.forEach((l,k)=>{somaData[k*8+6]=0});somaTex.needsUpdate=true;$('title').style.opacity=0;
  state.inside=false;state.diving=true;state.openT=1;satellites(-1);
  // back out the way we came: through the opening, pulling away while the gaze settles on the whole mind
  const end=c.clone().multiplyScalar(58).add(new V3(0,R*.4,0));
  const pts=[camera.position.clone(),c.clone().multiplyScalar(R*.62),c.clone().multiplyScalar(R*1.1),c.clone().multiplyScalar(R*2.6),end];
  const looks=[cam.look.clone(),c.clone().multiplyScalar(-R*.1),new V3(),new V3(),new V3()];
  tweenPath(pts,looks,38,REDUCED?.01:2.4,{kick:6,
    onT:e=>{if(e>.62)state.openT=0},
    done:()=>{state.openT=0;cam.mode='orbit';orbitFrom(camera.position,new V3());state.diving=false;done&&done();
      if(!done)hint('drag · turn the mind &nbsp; click a region · go inside<br>/ · search &nbsp; g · watch it grow &nbsp; s · coordinate layers &nbsp; t · theme')}});
}
function setFocusSoma(k){state.focusSoma=k;LM.forEach((_,j)=>{somaData[j*8+2]=j===k?1:(somaData[j*8+2]>0&&j!==k&&state.search?somaData[j*8+2]:0)});somaTex.needsUpdate=true}
function somaWorld(k){return somaPos[k].clone()}
function landmarkHTML(k,deep){const l=LM[k];const be=lmBest[k];
  const counts=l.evidence_counts?{...l.evidence_counts}:{};if(!l.evidence_counts)l.evidence.forEach(e=>counts[e.kind]=(counts[e.kind]||0)+1);
  const ev=Object.entries(counts).sort((a,b)=>(EVID[b[0]]||0)-(EVID[a[0]]||0)).map(([kd,n])=>`<span class="${kd==='user'?'u':''}">${EVID_WORD[kd]||kd}${n>1?' ×'+n:''}</span>`).join(' · ')||'<span>no outside evidence yet</span>';
  const s=M.sById.get(l.session);
  // a short task's class is the task's own words (landmark._make_task_class): then the kind says nothing - leave it out
  const cw=CLUSTER_WORD[l.cls]||(l.cls==='bootstrap'?'how IRIS was built':/^domain_task_/.test(l.cls)?'a kind of task':/^toolpath_task_/.test(l.cls)?'a way that worked for a task':'');
  const how=claimHow(l);
  return `<div class="k">claim · ${l.tier==='candidate'?'still learning':'proven'}${l.permanent?' · permanent':''}${cw?' · '+esc(cw):''} · ${syncHTML(syncClaim(l))}</div>
    <div class="t">${esc(l.claim)}</div>
    <div class="m">${how?esc(how)+'<br>':''}${l.where?`in the project <em>${esc(l.where)}</em><br>`:''}sync = how strongly it is proven: ${ev}<br>used <em>${fmt(l.activations)}</em> times${l.last_activated?' · last used '+ago(l.last_activated):''} · ${l.last_verified?'last confirmed '+ago(l.last_verified):'not confirmed yet'}
    ${l.contradictions?`<br><span class="w">contradicted ${l.contradictions===1?'once':l.contradictions+' times'}</span>`:''}
    ${deep&&s?`<br>learned while: <em>${esc(s.objective)}</em>`:''}</div>
    ${deep&&s?`<span class="go" data-go="${s.id}">→ step into that strand</span>`:''}${deep&&opts.uses?`<span class="go" data-uses="${k}">→ every time it was used</span>`:''}${deep&&opts.correct?`<span class="go" data-ask="${k}">→ ask IRIS about it</span>`:''}${deep&&opts.correctTarget?`<span class="go" data-pin="${k}">→ pin it</span>`:''}${deep?correctionHTML(k):''}`}
// EVERY TIME IT WAS USED (UX-PLAN 7.4): the turns that were given this claim - the timeline lights the beads of their
// conversations (the others dim) and the breadcrumb counts them; Esc returns. The most direct answer to "is this claim
// worth anything?".
const uses={k:-1,ids:new Set(),n:0,helped:0,misled:0,chat:null};
function setBeadLight(ids){sess.forEach((s,i)=>{bA[i]=ids?(ids.has(s.id)?1:0):(s.exit==='live'?1:0)});beadGeo.attributes.aA.needsUpdate=true}
function showUses(k){const l=LM[k];if(!l||!opts.uses)return;
  opts.uses(l.id).then(r=>{const list=r.uses||[];uses.k=k;uses.n=r.total??list.length;uses.ids=new Set(list.map(u=>u.thread));
    uses.helped=list.filter(u=>u.outcome==='helped').length;uses.misled=list.filter(u=>u.outcome==='misled').length;
    // the newest use the backend could tie to a turn of a chat conversation: the crumb offers it in the chat
    const nu=list.find(u=>u.turn&&(M.sessions.find(s=>s.id===u.thread)?.messages||[]).length);uses.chat=nu?{conv:nu.thread,turn:nu.turn}:null;
    setBeadLight(uses.ids);setLens('timeline');crumbKey='';
    hint(`every time IRIS was given this claim: <em>${fmt(uses.n)}</em> turn${uses.n===1?'':'s'}${uses.helped?` · ${fmt(uses.helped)} helped`:''}${uses.misled?` · <span class="w">${fmt(uses.misled)} misled</span>`:''} &nbsp; esc · back`)})
   .catch(err=>hint(esc(err?.message||'the uses could not be read')))}
function clearUses(){if(uses.k<0)return false;uses.k=-1;uses.ids=new Set();uses.chat=null;setBeadLight(null);crumbKey='';return true}
// A STRAND'S OWN CORRECTIONS (MEMORY-SURFACE-BUILD 5): in its corridor, "forget what IRIS learned here" (claims whose
// only evidence is this strand are absorbed, undoable 10 min) and "purge" (its text is removed for good: two clicks).
let purgeArm=0;
function strandAction(act,id,el){if(!opts.correctTarget)return;
  if(act==='purge'&&nowS()-purgeArm>4){purgeArm=nowS();el.textContent='click again to purge for good - it cannot be undone';return}
  el.textContent='working…';opts.correctTarget(act==='purge'?'purge':'forget_learned','strand:'+id,act==='purge'?{confirm:id}:{})
    .then(r=>{const a=r.after||{};el.textContent=act==='purge'?`purged · ${fmt(Object.values(a.rows_changed||{}).reduce((x,y)=>x+y,0))} rows`:`forgot ${fmt(a.claims_absorbed||0)} claim${a.claims_absorbed===1?'':'s'} · undo it in your corrections`;drawMine(true)})
    .catch(err=>{el.textContent=err?.message||'it did not take'})}
// A PIN'S CARD (MEMORY-SURFACE-BUILD 5): click a pin - its card, with unpin and hold in context / release (the pin
// store's own methods, through /api/memory/correct; undo in your corrections).
function focusPin(pk){const p=PINS[pk];if(!p)return;if(slots.focus)slots.focus.key=null;
  const acts=opts.correctTarget?`<div class="acts"><a data-pinact="${p.held?'release':'hold'}" data-pk="${pk}">${p.held?'release it from context':'hold it in context'}</a> · <a data-pinact="unpin" data-pk="${pk}">unpin</a></div>`:'';
  setAnno('focus','pinf'+pk,()=>project(pinInfo[pk].tip),pinHTML(pk)+acts,{cell:true,col:pinType(p.type).col});clearAnno('hover')}
function pinAction(pk,act,el){const p=PINS[pk];if(!p||!opts.correctTarget)return;el.textContent='working…';
  opts.correctTarget(act,'pin:'+p.id).then(r=>{const a=r.after||{};if(a.held!=null)p.held=!!a.held;
    el.textContent=act==='unpin'?'unpinned · undo it in your corrections':(p.held?'held in context':'released');drawMine(true)})
   .catch(err=>{el.textContent=err?.message||'it did not take'})}
// CORRECTIONS v1 (MEMORY-SURFACE-BUILD section 5): on a focused claim, "that's right / that's wrong / forget this".
// The backend writes each one as YOUR evidence and answers with the claim before and after; the card and the claim's
// look change only from that answer (never optimistic). Undo for 10 minutes. Real memory only (opts.correct).
const corr={};   // claim index -> {id, action, until} | {busy} | {error}
const CORR_WORD={confirm:'you marked this right',wrong:'you marked this wrong',forget:'you asked IRIS to forget this'};
function correctionHTML(k){if(!opts.correct)return '';const c=corr[k];
  if(c?.busy)return `<div class="acts">saving…</div>`;
  if(c?.id&&c.until>nowS())return `<div class="acts"><span class="u">${CORR_WORD[c.action]}</span> · <a data-undo="${k}">undo (${Math.max(1,Math.ceil((c.until-nowS())/60))} min)</a>${c.error?`<br><span class="w">${esc(c.error)}</span>`:''}</div>`;
  return `<div class="acts"><a data-correct="confirm" data-k="${k}">that's right</a> · <a data-correct="wrong" data-k="${k}">that's wrong</a> · <a data-correct="forget" data-k="${k}">forget this</a>${c?.error?`<br><span class="w">${esc(c.error)}</span>`:''}</div>`}
function showClaimCard(k){if(state.focusSoma!==k||!slots.focus)return;slots.focus.key=null;
  setAnno('focus','soma'+k,()=>project(somaWorld(k)),landmarkHTML(k,true),{hot:true,...lmCell(k)})}
function applyClaimState(k,st,userDelta){const l=LM[k];if(!l||!st)return;
  l.tier=st.tier||l.tier;l.contradictions=st.contradictions||0;
  if(userDelta>0)l.evidence.push({kind:'user',at:nowS()});
  else if(userDelta<0){const i=l.evidence.map(e=>e.kind).lastIndexOf('user');if(i>=0)l.evidence.splice(i,1)}
  if(userDelta&&l.evidence_counts)l.evidence_counts.user=Math.max(0,(l.evidence_counts.user||0)+userDelta);
  lmBest[k]=bestEvidence(l);
  somaData[k*8+3]=st.absorbed?0:(l.tier==='candidate'?.42:1);somaData[k*8+5]=l.tier==='candidate'?1:0;somaData[k*8+7]=l.contradictions>0?1:0;
  somaTex.needsUpdate=true}
function runCorrection(k,action){const l=LM[k];if(!l||!opts.correct||corr[k]?.busy)return;corr[k]={busy:true};showClaimCard(k);
  opts.correct(action,'claim:'+l.id).then(r=>{const kk=M.lmIndex.get(r.landmark_id)??k;
    applyClaimState(kk,r.after,action==='confirm'?1:0);if(action==='confirm'&&LM[kk])LM[kk].last_verified=nowS();   // the backend wrote it
    corr[kk]={id:r.correction_id,action,until:r.undo_until};if(kk!==k)delete corr[k];
    showClaimCard(kk);drawMine(true)})
   .catch(err=>{corr[k]={error:err?.message||'the memory did not take it'};showClaimCard(k)})}
function runUndo(k,id){const c=corr[k];id=id||c?.id;if(!id||!opts.undo)return;if(c)corr[k]={...c,busy:true};showClaimCard(k);
  opts.undo(id).then(r=>{const kk=M.lmIndex.get(r.landmark_id)??k;const was=corr[kk]?.action||mine.list.find(x=>x.correction_id===id)?.action;
    applyClaimState(kk,r.after,was==='confirm'?-1:0);delete corr[kk];showClaimCard(kk);drawMine(true)})
   .catch(err=>{if(c)corr[k]={...c,busy:false,error:err?.message||'undo failed'};showClaimCard(k)})}
// "your corrections": a line above the live line; it opens the recent ones (newest first), each undoable while it can be
const mine={open:false,list:[]};
const mineEl=document.createElement('div');mineEl.id='mine';$('hud').appendChild(mineEl);
function drawMine(reload){if(!opts.corrections){mineEl.style.display='none';return}
  if(reload)opts.corrections().then(r=>{mine.list=r.corrections||[];drawMine(false)}).catch(()=>{});
  const live=mine.list.filter(c=>!c.undone);
  mineEl.innerHTML=(mine.open?`<div class="list">${mine.list.length?mine.list.slice(0,12).map(c=>{
    const k=M.lmIndex.get(c.landmark_id),can=!c.undone&&c.undo_until>nowS();
    return `<div class="row${c.undone?' gone':''}"><span class="u">${esc(CORR_WORD[c.action]||c.action)}</span> · ${ago(c.ts)}${c.undone?' · undone':''}<br><span class="t">${esc(c.claim||'')}</span>${can?` <a data-undo-id="${esc(c.correction_id)}" data-k="${k??-1}">undo</a>`:''}${k!=null?` <a data-claim="${k}">show</a>`:''}</div>`}).join(''):'<div class="row">none yet</div>'}</div>`:'')+`<a class="head">your corrections · ${fmt(live.length)}${mine.open?' ▾':''}</a>`}
mineEl.addEventListener('click',e=>{const u=e.target.closest('[data-undo-id]');if(u){runUndo(+u.dataset.k,u.dataset.undoId);return}
  const c=e.target.closest('[data-claim]');if(c){focusRef('claim:'+LM[+c.dataset.claim].id);return}
  if(e.target.closest('.head')){mine.open=!mine.open;drawMine(mine.open)}});
drawMine(true);
annosEl.addEventListener('click',e=>{
  const cr=e.target.closest('[data-correct]');if(cr){runCorrection(+cr.dataset.k,cr.dataset.correct);return}
  const us=e.target.closest('[data-uses]');if(us){showUses(+us.dataset.uses);return}
  const pa=e.target.closest('[data-pinact]');if(pa){pinAction(+pa.dataset.pk,pa.dataset.pinact,pa);return}
  const pn=e.target.closest('[data-pin]');if(pn){const l=LM[+pn.dataset.pin];if(l&&opts.correctTarget)opts.correctTarget('pin','claim:'+l.id)
    .then(()=>{pn.textContent='pinned · undo it in your corrections';drawMine(true)}).catch(err=>{pn.textContent=err?.message||'the pin did not take'});return}
  // ask IRIS about a claim (UX-PLAN 4.6): a #claim reference chip in the chat's composer - an address, never the content
  const ak=e.target.closest('[data-ask]');if(ak){const l=LM[+ak.dataset.ask];if(l)window.dispatchEvent(new CustomEvent('iris:open_conversation',
    {detail:{ref:{address:'claim:'+l.id,label:'claim · '+(l.claim.length>48?l.claim.slice(0,47)+'…':l.claim)}}}));return}
  const un=e.target.closest('[data-undo]');if(un){runUndo(+un.dataset.undo);return}
  if(e.target.closest('[data-rewind]')){if(tunnel){selectThread(-1);cam.tpT=.012;cam.idle=-6}return}
  if(e.target.closest('[data-home]')){exitTunnel();return}
  const g=e.target.closest('[data-go]');if(!g)return;const s=M.sById.get(g.dataset.go);if(s)enterTunnel(s)});
function flyToSoma(k){
  const p=somaWorld(k);const back=camera.position.clone().sub(p).normalize();const to=p.clone().addScaledVector(back,R*.16);
  setFocusSoma(k);tweenTo(to,p,64,1.1,()=>{cam.mode='fly';flyFrom(camera.position,p)});
  setAnno('focus','soma'+k,()=>project(somaWorld(k)),landmarkHTML(k,true),{hot:true,...lmCell(k)});clearAnno('hover');
  // evidence satellites orbit the focused thought
  satellites(k)}
const satGroup=new THREE.Group();scene.add(satGroup);let satFor=-1;
function satellites(k){satGroup.clear();satFor=k;if(k<0)return;
  LM[k].evidence.forEach((e,i)=>{const s=new THREE.Sprite(new THREE.SpriteMaterial({map:GLOW,color:new THREE.Color(EVID_COL[e.kind]||'#fff'),transparent:true,
    opacity:.95,blending:THREE.AdditiveBlending,depthWrite:false}));s.scale.setScalar(e.kind==='user'?R*.016:R*.01);
    s.userData={ph:i/LM[k].evidence.length*6.28,ax:new V3(gauss(),gauss(),gauss()).normalize(),r:R*(.045+.012*i)};satGroup.add(s)})}
function updateSatellites(t){if(satFor<0)return;const c=somaWorld(satFor);satGroup.children.forEach(s=>{const u=s.userData;
  const v=new V3(Math.cos(t*.8+u.ph),Math.sin(t*.8+u.ph),0).multiplyScalar(u.r).applyAxisAngle(u.ax,1.1);s.position.copy(c).add(v)})}
const DARK=new THREE.Color(0x020306),VOID=new THREE.Color('#dfe8ee'),voidCol=new THREE.Color();
function flash(on,ms=260){const f=$('flash');f.style.transition=`opacity ${ms}ms`;f.style.opacity=on?.85:0}
function enterTunnel(s){
  if(cam.mode==='tunnel'){disposeTunnel()}
  state.from=state.inside?'cortex':state.lens;
  clearAnno('focus');clearAnno('hover');satellites(-1);
  const goIn=()=>{flash(true,REDUCED?1:220);setTimeout(()=>{
      if(state.inside){state.inside=false;state.openT=0;LM.forEach((l,k)=>{somaData[k*8+6]=0});somaTex.needsUpdate=true;state.focusDimT=0}
      showMind(false);tunnel=buildTunnel(s);rail.build(tunnel);state.voidT=REDUCED?0:1;tunnel.tileU.uAsm.value=REDUCED?1:0;cortex.visible=false;tcv.classList.remove('on');tissue.on=false;tissue.t=0;
      cam.tween=null;cam.mode='tunnel';cam.tp=0;cam.tpT=.012;cam.idle=0;camera.fov=95;cam.fovT=72;camera.updateProjectionMatrix();
      const T=$('title');const end=s.ended?`${span(s.ended-s.started)} · ${s.exit==='drift'?'drifted before it finished':'ended well'}`:'happening now';
      T.innerHTML=`${esc(s.objective)}<small>${ago(s.started)} · ${end} · ${fmt(s.events.length)} moments · ${s.episodes.length} tasks · ${syncHTML(syncSession(s))}</small>`;T.style.opacity=1;
      $('scrub').classList.remove('on');
      document.querySelectorAll('#lenses a').forEach(a=>a.classList.remove('on'));
      hint('scroll / w s · travel through the strand &nbsp; ← → · claim to claim<br>hover · read a message or moment &nbsp; click a claim · follow its thread &nbsp; esc · back');
      flash(false,REDUCED?1:700)},REDUCED?0:240)};
  if(state.lens==='timeline'&&!state.inside&&cam.mode==='orbit'){const bi=sess.indexOf(s);const p=new V3(0,helixY(sessS(s)),0);
    tweenTo(p.clone().add(camera.position.clone().sub(p).normalize().multiplyScalar(4)),p,22,.9,goIn)}
  else goIn();
}
function exitTunnel(done){
  flash(true,REDUCED?1:200);
  setTimeout(()=>{disposeTunnel();state.voidT=0;renderer.setClearColor(DARK,1);cortex.visible=true;clearAnno('hover');cam.mode='orbit';camera.fov=38;cam.fovT=38;camera.updateProjectionMatrix();
    const back=state.from||'cortex';state.lens='';flash(false,REDUCED?1:600);
    cam.tween=null;orbitFrom(new V3(0,R*.4,R*5.8),new V3());
    // put the camera at the orbit NOW (under the flash): orbitFrom only sets targets, and a flight started right after
    // (open in the mind -> dive) began from the tunnel, ~2,800 units away - half a second of black while it flew back
    camera.position.set(0,R*.4,R*5.8);cam.look.set(0,0,0);camera.lookAt(cam.look);
    setLens(back==='cortex'||!back?'cortex':back);done&&done()},REDUCED?0:220);
}

// ═══════════════════════════════════════════════════════════════════════════
// 12. the agent at work (live tap: memory_event / landmark_update / episode_completed / oracle_decision)
//     In the app these arrive as iris:ws_message (MEMORY-DASHBOARD-DESIGN §10.1); here a replay drives them.
// ═══════════════════════════════════════════════════════════════════════════
const queue=[];const after=(s,fn)=>queue.push({at:clock.elapsedTime+s,fn});
let nextEv=1.2,nextRecall=5,nextPromo=18,nextCorr=34,nextDec=2,nextMote=6,nextQ=8,qIx=0;
function regionPoint(fi){return regC[fi].clone().add(new V3(gauss(),gauss(),gauss()).multiplyScalar(.12)).normalize().multiplyScalar(R)}
function pickSoma(){if(!NL)return -1;const k=Math.floor(Math.pow(rng(),1.6)*NL);return LM.map((l,i)=>[i,l.activations]).sort((a,b)=>b[1]-a[1])[k%NL][0]}
const somaByReg=REG.map((_,ri)=>LM.map((l,i)=>l.dom===ri?i:-1).filter(i=>i>=0));
function pickSomaIn(fi){const s=somaByReg[fi];return s&&s.length?s[Math.floor(rng()*s.length)]:pickSoma()}
function emit(e){
  e.ts=nowS();tick(e);
  // activity rises with each moment but is capped, so a busy region glows without washing out the orb
  // the moment lands in its DOMAIN's territory; its family is the colour of the activity there
  const fi=FAMI[e.family]??0,di=regOf(e.domain||(e.landmark!=null&&LM[e.landmark]?LM[e.landmark].domain:'general'));
  regAct[di]=Math.min(regBase[di]+.45,regAct[di]+.22);
  if(e.valence==='sets_back')state.warn=Math.min(1,(state.warn||0)+.7);
  if(e.evidence==='user'){shockwave()}
  if(cam.mode==='tunnel'&&tunnel&&tunnel.session.exit==='live'){
    const n=tunnel.nodes;const a=tunnel.curve.getPointAt(Math.max(0,cam.tp)).add(TUN_OFF),b=tunnel.curve.getPointAt(.99).add(TUN_OFF);
    spark(a,b,FAM[fi].color,{speed:.5,gain:1.2,bend:1,jit:.3});return}
  if(!cortex.visible)return;
  // A MOMENT is a spark (the key draws it the same way): it leaves IRIS's mind at the core, runs out to its territory,
  // flashes on the skin where it lands (the ripple) and fades. When it touches a claim, a second, fainter spark runs
  // down that claim's arbor arm and wakes it.
  const wired=e.landmark!=null&&e.landmark<NL?e.landmark:pickSomaIn(di);const k=wired;
  const col=e.valence==='sets_back'?'#ff4a3d':e.evidence==='user'?'#ffffff':FAM[fi].color;
  if(!cortexShown())return;
  const land=k>=0&&LM[k].dom===di?somaAnchor[k].clone():regionPoint(di),core=land.clone().normalize().multiplyScalar(R*.1);
  const ctrl=core.clone().lerp(land,.55).add(new V3(gauss(),gauss(),gauss()).multiplyScalar(R*.14));
  const wake=()=>{if(k<0)return;somaData[k*8]=Math.min(1,somaData[k*8]+.35);somaTex.needsUpdate=true};
  spark(core,land,col,{speed:.85,gain:.45+(EVID[e.evidence]??.2)*.9,ctrl,jit:.008,
    done:()=>{impact(land.clone().normalize(),col);
      if(k>=0&&LM[k].dom===di)spark(somaAnchor[k],somaWorld(k),col,{speed:.9,gain:.3,ctrl:somaCtrl[k],jit:.006,done:wake});else wake()}});
}
function cortexShown(){return cortex.visible&&(state.lens==='cortex'||state.inside)}
function recallChain(){
  const k=pickSoma();if(k<0)return;const mi=FAMI.memory;
  const ev=lab=>({family:'memory',label:lab,actor:'agent',evidence:lab==='RECALL_HELPED'?'completion':'claim',valence:lab==='RECALL_MISLED'?'sets_back':'advances',landmark:k});
  emit(ev('RECALL_DELIVERED'));somaData[k*8]=.4;somaTex.needsUpdate=true;if(cortexShown())reachOut(k);
  after(1.7,()=>{emit(ev('RECALL_USED'));somaData[k*8]=.85;somaTex.needsUpdate=true;if(cortexShown())thread(somaAnchor[k],somaWorld(k),FAM[mi].color,4.5)});
  after(3.9,()=>{const helped=rng()<.8;emit(ev(helped?'RECALL_HELPED':'RECALL_MISLED'));
    if(helped){somaData[k*8+1]=1;LM[k].activations++;LM[k].last_activated=nowS();if(cortexShown())pulseRing(somaWorld(k),'#ffffff',R*.22)}
    else{somaData[k*8+4]=1;LM[k].contradictions++;somaData[k*8+7]=1;if(cortexShown())pulseRing(somaWorld(k),'#ff4a3d',R*.18)}
    somaTex.needsUpdate=true;
    if(state.focusSoma===k||slots.hover?.key==='soma'+k){const s=slots[state.focusSoma===k?'focus':'hover'];s.key=null;setAnno(state.focusSoma===k?'focus':'hover','soma'+k,()=>project(somaWorld(k)),landmarkHTML(k,state.focusSoma===k),{hot:true,...lmCell(k)})}});
}
function promote(){const c=LM.map((l,i)=>[l,i]).filter(([l])=>l.tier==='candidate');if(!c.length)return;const [l,k]=pick(c);
  l.tier='landmark';l.evidence.push({kind:pick(['test','completion','recurrence']),at:nowS(),session:l.session});lmBest[k]=bestEvidence(l);
  somaData[k*8+5]=0;state.grow=state.grow||[];state.grow.push(k);somaData[k*8+1]=1;somaTex.needsUpdate=true;
  emit({family:'memory',label:'LANDMARK_PROMOTED',actor:'agent',evidence:'test',valence:'advances',landmark:k});
  if(cortexShown())pulseRing(somaWorld(k),THEMES[themeIdx][1],R*.3,2)}
function userCorrection(){emit({family:'feedback',label:pick(['CORRECTION','CONFIRMATION']),actor:'user',evidence:'user',valence:'advances'})}
function oracleDecision(){if(!ORC.length)return;const w=ORC.map((o,i)=>[i,o.rows]);const i=weighted(w);const o=ORC[i];
  const conf=clamp(.5+gauss()*.2+(o.state==='enforced'?.25:0),.05,.99);const acted=o.state==='enforced'||(o.state==='sampled'&&rng()<.05);
  state.secPulse[i]=1;state.pupilT=.75+conf*.6;state.lastDecision={o,conf,acted}}
state.secPulse=new Array(MAXSEC).fill(0);state.pupilT=1;state.openT=0;state.focusDimT=0;state.warn=0;
// FOLLOW: the backend's live taps (backend/utils/memory_live: memory_event, landmark_update, oracle_decision, batched
// per 250 ms) drive the same effects the demo replay does - on the real memory only, and only what happened. Moments
// play at most FOLLOW_RATE a second from a bounded queue, so a burst never floods the scene. Lost messages
// (payload.dropped) are said, with a reload: the model on screen is then behind the store.
const FOLLOW_Q_MAX=40,FOLLOW_RATE=4;
const followEl=document.createElement('a');followEl.id='follow';$('hud').appendChild(followEl);
function drawFollow(){followEl.style.display=USE_REAL?'':'none';
  followEl.innerHTML=`<span class="dot${follow.on?' on':''}"></span>${follow.on?'following IRIS live':'live paused'} · f <i data-replay title="play the newest recorded turn again (r)">· replay the last turn</i>`+
    (follow.missed?` <b title="reload the memory">· missed ${fmt(follow.missed)} · reload</b>`:'')}
function setFollow(on){follow.on=on;follow.q.length=0;try{localStorage.setItem('iris.memory.follow',on?'1':'0')}catch(e){}drawFollow()}
followEl.addEventListener('click',e=>{if(e.target.closest('[data-replay]')){replayTurn();return}if(follow.missed&&e.target.closest('b')){opts.reload?.();return}setFollow(!follow.on)});
drawFollow();
// THE LIVE GRAMMAR (UX-PLAN 6.3, phase 6): one direction per kind of act, the same in every view.
//   memory delivered to a step (RECALL_DELIVERED / USED)  INWARD   a spark from the claim (or its territory) to the core
//   a step records a moment                             OUTWARD  a spark from the core to its territory (emit)
//   recall verified (RECALL_HELPED) / misled            a quiet ring on the claim / its desync glitch
//   a claim promoted / dissolved                        graduation ring / it loosens and fades (landmark_update)
//   the Oracle decides                                  RAY in the Oracle view; elsewhere a ticker line only
// At most FX_MAX effects at once: the rest are said in the ticker only, so nothing builds up. Follow mode also moves
// the camera like an operator: after 20 s without input, the cortex turns toward where IRIS touches memory.
const FX_MAX=6;const fx={live:0};
function fxTake(dur){if(fx.live>=FX_MAX)return false;fx.live++;setTimeout(()=>{fx.live=Math.max(0,fx.live-1)},(dur||1.8)*1000);return true}
function followCamera(e){if(!follow.on||cam.mode!=='orbit'||state.lens!=='cortex'||state.inside||cam.tween||cam.idle<20)return;
  const v=regC[regOf(e.domain||'general')].clone().normalize();cam.azT=cam.az+angWrap(Math.atan2(v.x,v.z)-cam.az);cam.elT=clamp(Math.asin(clamp(v.y,-1,1))*.8,-1,1)}
function liveEmit(e){
  const k=e.landmark!=null&&e.landmark<NL?e.landmark:-1;followCamera(e);
  if(e.label==='RECALL_DELIVERED'||e.label==='RECALL_USED'){tick(e);   // INWARD: memory -> mind
    if(!cortexShown()||!fxTake())return;const from=k>=0?somaWorld(k):regionPoint(regOf(e.domain||'general'));
    if(k>=0){somaData[k*8]=Math.min(1,somaData[k*8]+.35);somaTex.needsUpdate=true}
    spark(from,from.clone().multiplyScalar(.1),FAM[FAMI.memory].color,{speed:.85,gain:.35+(EVID[e.evidence]??.2)*.6,jit:.008});return}
  if(e.label==='RECALL_HELPED'||e.label==='RECALL_MISLED'){tick(e);if(k<0)return;
    if(e.label==='RECALL_HELPED'){if(cortexShown()&&fxTake(1.4))pulseRing(somaWorld(k),'#ffffff',R*.16)}
    else{somaData[k*8+4]=1;somaTex.needsUpdate=true}return}   // the desync glitch (slot 4) fades in the frame loop; a misled recall is not a contradiction
  if(!fxTake()){tick(e);return}   // over the cap: the ticker says it, the scene does not
  emit(e)}                         // OUTWARD (and everything else): core -> territory
// the Oracle outside its own view: one ticker line, no effect
function tickOracle(d){const c=d.consumer||'';tickLines[0].innerHTML=tickLines[1].innerHTML;
  tickLines[1].innerHTML=`<span class="dot" style="background:#7fe8ff"></span><span class="tx" style="color:rgba(212,236,246,.6)">the Oracle · ${esc(oracleWord(c))}</span><span style="color:var(--faint)"> · ${Math.round((+d.confidence||0)*100)}% sure${(d.options||[]).length?' · '+esc(String(d.options[0].name).replace(/_/g,' ')):''}${d.acted==='enforced'?' · it acted':''}</span>`}
// REPLAY (phase 6 DONE: a recorded turn replays through the same grammar): r plays the newest recorded turn's own
// events from this memory, in order, at the live pace - nothing is invented.
function replayTurn(){const by=new Map();for(const e of M.events){if(!e.episode||!e.ts)continue;const a=by.get(e.episode)||[];a.push(e);by.set(e.episode,a)}
  let best=null;for(const [ep,a] of by)if(a.length>=3&&(!best||a[a.length-1].ts>best.last))best={ep,a,last:Math.max(...a.map(x=>x.ts))};
  if(!best){hint('no recorded turn with enough moments to replay');return}
  const evs=best.a.slice().sort((x,y)=>x.ts-y.ts).slice(0,FOLLOW_Q_MAX);follow.q.length=0;
  for(const e of evs)follow.q.push({family:e.family,label:e.label,valence:e.valence,actor:e.actor,evidence:e.evidence,domain:e.domain,landmark:e.landmark});
  const ep=M.epById?.get(best.ep);tickLines[0].innerHTML=tickLines[1].innerHTML;
  tickLines[1].innerHTML=`<span class="dot" style="background:#ffb547"></span><span class="tx">replaying a recorded turn · ${fmt(evs.length)} moments</span><span style="color:var(--faint)"> · ${esc(ep?.summary?String(ep.summary).slice(0,60):ago(best.last))}</span>`}
// THE LIVE DOT (UX-PLAN 6.3 / 13): one meaning everywhere - IRIS is working on a turn right now. The memory hears it as
// live taps; the dot stays while they keep coming (LIVE_DOT_S after the last), whether or not follow mode is on.
const LIVE_DOT_S=12;let liveAt=-1e9;
function liveMsg(msg){
  if(!USE_REAL||!msg)return;const p=msg.payload||{};
  if(msg.type==='memory_event'||msg.type==='oracle_decision')liveAt=performance.now();
  if(p.dropped>0){follow.missed+=p.dropped;drawFollow()}
  if(!follow.on)return;
  if(msg.type==='memory_event'){for(const r of p.events||[]){
    if(!cursorNow()){follow.unseen++;continue}
    if(follow.q.length>=FOLLOW_Q_MAX)follow.q.shift();   // the newest moments win
    follow.q.push({family:r.family,label:r.label,valence:r.valence,actor:r.actor,evidence:r.evidence,
      domain:String(r.topic_domain||'general').split('/')[0],landmark:r.landmark_id&&M.lmIndex.has(r.landmark_id)?M.lmIndex.get(r.landmark_id):null})}}
  else if(msg.type==='landmark_update'){for(const u of p.updates||[]){const k=M.lmIndex.get(u.landmark_id);if(k==null||!LM[k])continue;const l=LM[k];
    if(u.tier)l.tier=u.tier;if(u.activation_count!=null)l.activations=u.activation_count;
    if(u.kind==='activated'){l.last_activated=u.ts;somaData[k*8]=Math.min(1,somaData[k*8]+.35);somaTex.needsUpdate=true}
    if(u.kind==='promoted'&&cursorNow()&&cortexShown()&&fxTake(2))pulseRing(somaWorld(k),THEMES[themeIdx][1],R*.3,2);   // graduation
    if(u.kind==='dissolved'||u.kind==='merged'){somaData[k*8+3]=0;somaTex.needsUpdate=true}}}                             // dissolution
  else if(msg.type==='oracle_decision'){for(const d of p.decisions||[]){const i=ORC.findIndex(o=>o.consumer===d.consumer);if(i<0)continue;
    if(state.lens!=='oracle')tickOracle(d);
    const conf=clamp(+d.confidence||0,0,1);state.secPulse[i]=1;state.pupilT=.75+conf*.6;
    state.lastDecision={o:ORC[i],sec:i,conf,acted:d.acted==='enforced',chosen:d.chosen,options:Array.isArray(d.options)?d.options:[],t:clock.elapsedTime};
    pupilDecision(state.lastDecision)}}}
function simulate(dt){
  const t=clock.elapsedTime;
  for(let i=queue.length-1;i>=0;i--)if(queue[i].at<=t){const q=queue.splice(i,1)[0];q.fn()}
  if(follow.q.length&&t>=follow.next){follow.next=t+1/FOLLOW_RATE;liveEmit(follow.q.shift())}
  // A REAL memory shows only what happened. The replay below invents activity (old moments re-emitted as live, recall
  // chains, promotions that change a claim's tier, corrections, Oracle decisions); it is the demo's stand-in for the
  // live tap and must never run on data/memory.db (found 2026-10-22: the surface showed "remembering this helped" and
  // promoted claims that were never promoted). Real activity arrives from the backend's live messages only.
  if(USE_REAL)return;
  if(t>nextEv){nextEv=t+rand(.9,2.4);const e=pick(M.events.length?M.events:[{family:'knowledge',label:'OBSERVED',actor:'tool',evidence:'claim',valence:'neutral'}]);
    emit({...e,landmark:e.family==='memory'?e.landmark:null})}
  if(t>nextRecall){nextRecall=t+rand(8,13);recallChain()}
  if(t>nextPromo){nextPromo=t+rand(22,34);promote()}
  if(t>nextCorr){nextCorr=t+rand(40,60);userCorrection()}
  if(t>nextDec){nextDec=t+rand(1.4,3.2);oracleDecision()}
  // the guard's log, replayed oldest first at a calm cadence (each row names when it truly happened)
  if(t>nextQ){nextQ=t+rand(6,10);if(M.quorum.length&&cortexShown()){immuneSignal(M.quorum[qIx%M.quorum.length]);qIx++}}
  if(t>nextMote&&motes.length){nextMote=t+rand(5,8);const m=pick(motes);
    if(m.state==='in'){m.state='out';m.rT=R*.58;emit({family:'memory',label:'OFFLOADED',actor:'agent',evidence:'claim',valence:'neutral'})}
    else{m.state='in';m.rT=R*.3;emit({family:'memory',label:'RESTRETCHED',actor:'agent',evidence:'claim',valence:'advances'})}}
}


// ═══════════════════════════════════════════════════════════════════════════
// 13. input
// ═══════════════════════════════════════════════════════════════════════════
const ray=new THREE.Raycaster();
function regionAt(x,y){
  ray.setFromCamera(new THREE.Vector2(x/innerWidth*2-1,-(y/innerHeight)*2+1),camera);
  const hit=ray.ray.intersectSphere(new THREE.Sphere(new V3(),R),new V3());if(!hit)return -1;
  const n=hit.clone().normalize();let best=-1,bd=1e9;
  regC.forEach((c,i)=>{const d=Math.acos(clamp(n.dot(c),-1,1));if(d<regRad[i]&&d/regRad[i]<bd){bd=d/regRad[i];best=i}});return best}
function nearestScreen(list,x,y,maxD){let best=-1,bd=maxD;list.forEach((p,i)=>{if(!p)return;const s=project(p);if(!s.front)return;const d=Math.hypot(s.x-x,s.y-y);
  if(d<bd){bd=d;best=i}});return best}
function coreHit(x,y){const c=project(new V3()),e=project(new V3(R*.2,0,0).applyQuaternion(camera.quaternion));return Math.hypot(x-c.x,y-c.y)<Math.abs(e.x-c.x)}
// pins and nodes answer a hover with a swelling cell at their own point (cortex level only)
function hoverThing(x,y){
  const ok=state.inside?p=>p.distanceTo(camera.position)<R*1.1:p=>p.dot(camera.position)>0;
  const pk=nearestScreen(pinInfo.map(q=>ok(q.tip)?q.tip:null),x,y,state.inside?15:9);   // smaller from outside: the territories come first
  if(pk>=0){canvas.style.cursor='default';setAnno('hover','pin'+pk,()=>project(pinInfo[pk].tip),pinHTML(pk),{cell:true,col:pinType(PINS[pk].type).col});return true}
  // nodes are inside the orb, on the layer shells: from outside they are hovered only with the layers shown (s) or
  // singled out in the key - otherwise they covered the whole front of the orb and no territory could be clicked
  const nodesOn=state.inside||state.showSpaces||keyFocus==='node';
  const nk=nodesOn?nearestScreen(nodePos.map(p=>ok(p)?p:null),x,y,11):-1;
  if(nk>=0){canvas.style.cursor='default';setAnno('hover','node'+nk,()=>project(nodePos[nk]),nodeHTML(nk),{cell:true,col:chanTint(NDS[nk].chan)});return true}
  if(slots.hover?.key&&/^(pin|node)/.test(slots.hover.key))clearAnno('hover');
  return false}
function hover(x,y){
  state.hoverReg=-1;skinMat.uniforms.uHoverReg.value=-1;state.hoverSec=-1;skinMat.uniforms.uHoverSec.value=-1;beadMat.uniforms.uHover.value=-1;
  canvas.style.cursor='default';
  if(cam.tween||state.diving)return;
  if(cam.mode==='tunnel'&&tunnel){
    const near=(w,d)=>w.distanceTo(camera.position)<d?w:null;
    const k=nearestScreen(tunnel.items.map(n=>near(n.world,70)),x,y,14);
    const st=nearestScreen(tunnel.stars.map(s=>near(s.world,90)),x,y,22);
    state.hoverDoor=null;
    if(st<0&&k<0){for(const [nm,d] of [['door',tunnel.door],['back',tunnel.back]]){const p=project(d.world);
      const e=project(d.world.clone().add(new V3(0,d===tunnel.door?4:1.5,0)));if(p.front&&Math.hypot(p.x-x,p.y-y)<Math.max(30,Math.abs(e.y-p.y))&&d.world.distanceTo(camera.position)<70){
        state.hoverDoor=nm;canvas.style.cursor='pointer';tunnelHighlight(null);
        const nx=tunnel.door.next;
        setAnno('hover','door-'+nm,()=>project(d.world),nm==='door'
          ?`<div class="k">doorway</div><div class="t">${nx?esc(nx.objective):'back to the timeline'}</div><div class="m">${nx?`the next strand of this thread · ${ago(nx.started)}`:'the last strand of its thread'}</div><span class="go">click · step through</span>`
          :`<div class="k">doorway</div><div class="t">back to the beginning of this thread</div><span class="go">click · return to its first moment</span>`,{hot:true});return}}}
    const pk=nearestScreen(tunnel.pins.map(b=>near(b.world,70)),x,y,16);
    if(pk>=0&&st<0&&k<0){const b=tunnel.pins[pk],p=b.p,t=pinType(p.type),later=p.refs.filter(r=>(r.t==='thread'||r.t==='session')&&r.id!==tunnel.session.id).length;
      canvas.style.cursor='default';tunnelHighlight(null);
      setAnno('hover','tpin'+pk,()=>project(b.world),`<div class="k">${t.word} · ${p.held?'held in context right now':'resting'}${p.type==='checkpoint'?' · where this thread was paused':''}</div><div class="t">${esc(p.title)}</div>
        <div class="m">pinned ${ago(p.created)} · tied to <em>${p.links}</em> thing${p.links===1?'':'s'}${later?`<br>also used in <em>${later}</em> other thread${later===1?'':'s'}`:''}</div>`);return}  // the timeline keeps leader-line labels; cells are cortex-only
    const gt=nearestScreen(tunnel.gates.map(g=>g.world.distanceTo(camera.position)<80?g.world:null),x,y,60);
    if(st>=0){const s=tunnel.stars[st];canvas.style.cursor='pointer';tunnelHighlight(s.item);
      setAnno('hover','star'+st,()=>project(s.world),landmarkHTML(s.li,false)+`<span class="go">${tunnel.sel===s.li?'enter · open this thought in the mind':'click · follow its thread'}</span>`,{hot:true});state.hoverStar=st;return}
    state.hoverStar=-1;
    if(k>=0){const n=tunnel.items[k];tunnelHighlight(n);canvas.style.cursor='default';
      if(n.type==='msg'){const m=n.m,mins=Math.max(0,Math.round((m.ts-tunnel.session.started)/60));
        setAnno('hover','item'+k,()=>project(n.world),`<div class="k">${m.role==='user'?'you':'IRIS'} · ${mins} min in · conversation</div>
          <div class="t">${m.text?esc(m.text):(m.role==='user'?'you wrote':'IRIS replied')+` · about ${Math.max(5,Math.round((m.len||60)/6))} words`}</div>
          <div class="m">linked to <em>${n.links.length}</em> moment${n.links.length===1?'':'s'} in memory${n.links.length?':<br>'+n.links.slice(0,4).map(l=>esc(readEvent(l.e))).join(' · '):''}</div>`,{hot:m.role==='user'});return}
      const e=n.e;const ep=M.epById.get(e.episode);const turn=n.links[0];
      setAnno('hover','item'+k,()=>project(n.world),`<div class="k">${FAM[FAMI[e.family]]?.word||'other'} · ${ago(e.ts)} · memory</div><div class="t">${esc(readEvent(e))}</div>
        <div class="m">${EVID_WORD[e.evidence]||'unconfirmed'} · ${e.valence==='advances'?'helped the goal':e.valence==='sets_back'?'<span class="w">set the goal back</span>':'neither helped nor hurt'}
        · by ${e.actor==='user'?'<span class="u">you</span>':e.actor==='agent'?'IRIS':e.actor==='tool'?'a tool':e.actor==='subagent'?'a helper':'the world'}
        ${turn?`<br>in the turn where ${turn.m.role==='user'?'you wrote':'IRIS replied'}${turn.m.text?': <em>'+esc(turn.m.text.slice(0,70))+'</em>':''}`:''}
        ${ep?`<br>during: <em>${esc(ep.summary)}</em>`:''}</div>`,{hot:e.evidence==='user'});return}
    tunnelHighlight(null);
    if(gt>=0){const g=tunnel.gates[gt],ep=g.ep;
      setAnno('hover','gate'+gt,()=>project(g.world),`<div class="k">task · ${ep.outcome==='running'?'running now':ep.outcome==='success'?'went well':ep.outcome==='partial'?'partly done':'did not work'}</div>
        <div class="t">${esc(ep.summary)}</div><div class="m">went well <em>${Math.round(ep.score*100)}</em> / 100 · took ${span(ep.duration/1)}
        ${ep.corrected?'<br><span class="u">you corrected IRIS here</span>':ep.confirmed?'<br>you confirmed this':''}
        ${ep.failure_reason?`<br><span class="w">${esc(ep.failure_reason)}</span>`:''}<br>what IRIS did: ${(ep.tools||[]).map(t=>t.replace(/_/g,' ')).join(' → ')}</div>`,{hot:ep.corrected});return}
    lingerClear('hover');return}
  if(state.lens==='artifacts'&&tissue.t>.5&&!state.inside){const i=tissueHit(x,y),th=i<0?threadHit(x,y):-1,cr=crumbHit(x,y);
    tissue.hover=i;tissue.hoverThread=th;const pt=i>=0||th>=0||!!cr;canvas.style.cursor=tcv.style.cursor=pt?'pointer':'default';
    if(i>=0&&tissue.focus<0&&tissue.cells[i].type==='item'){const c=tissue.cells[i];
      setAnno('hover','art'+i,()=>({x:c.cx,y:c.cy,front:true}),`<div class="k">${KIND_WORD[c.a.kind]||c.a.kind} · ${esc(c.a.folder||'unsorted')} · ${ago(c.a.ts)}</div><div class="t">${esc(c.a.name)}</div>`)}
    else lingerClear('hover');return}
  if(state.inside){
    const k=nearestScreen(LM.map((_,i)=>somaData[i*8+3]>0&&somaPos[i].distanceTo(camera.position)<R*1.1?somaWorld(i):null),x,y,16);state.hoverSoma=k;
    if(k>=0&&k!==state.focusSoma){canvas.style.cursor='pointer';setAnno('hover','soma'+k,()=>project(somaWorld(k)),landmarkHTML(k,false),lmCell(k));
      for(let j=0;j<NL;j++)if(j!==state.focusSoma)somaData[j*8+2]=j===k?1:0;somaTex.needsUpdate=true}
    else{if(k<0){if(!hoverThing(x,y))lingerClear('hover');for(let j=0;j<NL;j++)if(j!==state.focusSoma&&!state.search)somaData[j*8+2]=0;somaTex.needsUpdate=true}}
    return}
  if(state.lens==='cortex'){
    if(coreHit(x,y)){state.hoverCore=true;canvas.style.cursor='help';showMind(true);lingerClear('hover');return}
    state.hoverCore=false;showMind(false);
    if(hoverThing(x,y))return;
    const r=regionAt(x,y);state.hoverReg=r;skinMat.uniforms.uHoverReg.value=r;if(r>=0)canvas.style.cursor='pointer';return}
  if(state.lens==='timeline'&&state.turnZoom){const ti=nearestScreen(TURNS.map(t=>t.world),x,y,10);state.hoverTurn=ti;
    if(ti>=0){canvas.style.cursor='pointer';beadMat.uniforms.uHover.value=-1;state.hoverBead=-1;setAnno('hover','turn'+ti,()=>project(TURNS[ti].world),turnHTML(TURNS[ti]));return}}
  else state.hoverTurn=-1;
  if(state.lens==='timeline'){const k=nearestScreen(sess.map(s=>new V3(0,helixY(sessS(s)),0)),x,y,26);state.hoverBead=k;beadMat.uniforms.uHover.value=k;
    if(k>=0){const s=sess[k];canvas.style.cursor='pointer';buildSyncFor(s.id);syncU.uSel.value=-1;const rs=recSummary(s.id);
      const eps=s.episodes.map(id=>M.epById.get(id)).filter(Boolean);const corr=eps.some(e=>e.corrected);
      const done=eps.filter(e=>e.outcome!=='running'),good=done.filter(e=>e.outcome==='success').length;
      const ask=(s.messages||[]).find(m=>m.role==='user'&&m.text)?.text||eps[0]?.summary;   // what was asked, in the words used
      setAnno('hover','bead'+k,()=>project(new V3(0,helixY(sessS(s)),0)),`<div class="k">${s.ghost?'deleted in chat · ':outsideChat(s)?'outside chat · ':''}${ago(s.started)}${s.ended?' · '+span(s.ended-s.started):' · happening now'}</div><div class="t">${esc(s.objective)}</div>
        <div class="m">${ask&&ask!==s.objective?`asked: <em>${esc(ask.length>90?ask.slice(0,89)+'…':ask)}</em><br>`:''}${syncHTML(syncSession(s))} ${done.length?`· ${good} of ${done.length} tasks went well`:'· no task result yet'}<br>${fmt(s.events.length)} moments · ${eps.length} tasks${corr?' · <span class="u">you corrected IRIS here</span>':''}${s.exit==='drift'?' · <span class="w">drifted before it finished</span>':''}${rs?`<br>the memory gave it <em>${rs.refs}</em> earlier step${rs.refs===1?'':'s'} from <em>${rs.from}</em> strand${rs.from===1?'':'s'} ·${rs.helped} of ${rs.steps} helped${rs.misled?` · <span class="w">${rs.misled} misled</span>`:''}`:''}</div><span class="go">click · step inside</span>`)}
    else if(!syncHoverStrand(x,y))lingerClear('hover');return}
  if(state.lens==='oracle'){
    ray.setFromCamera(new THREE.Vector2(x/innerWidth*2-1,-(y/innerHeight)*2+1),camera);const p=new V3();
    if(ray.ray.intersectPlane(new THREE.Plane(new V3(0,0,1),0),p)){const r=p.length();
      if(r<=R*.28){state.hoverSec=-1;skinMat.uniforms.uHoverSec.value=-1;canvas.style.cursor='help';
        const n=pupilLive.recent.filter(t=>nowS()-t<60).length;
        setAnno('hover','pupil'+n,()=>{const c=project(new V3());return {x:c.x,y:c.y,front:true}},`<div class="k">the Oracle</div><div class="t">one small model, on this machine</div>
          <div class="m">it answers ONE question per decision, and reads its answer from its own scores - no text<br>it opens when it decides: each arc is an option, as long as how likely it found it<br>${n?`<em>${fmt(n)}</em> decision${n===1?'':'s'} in the last minute`:'no decision in the last minute'}</div>`);return}
      if(r>R*.28&&r<R*1.1){let a=Math.atan2(p.y,p.x)-Math.PI/2;a=((a%(Math.PI*2))+Math.PI*2)%(Math.PI*2);const sec=Math.floor(a/(Math.PI*2)*NSEC)%NSEC;
        state.hoverSec=sec;skinMat.uniforms.uHoverSec.value=sec;canvas.style.cursor='pointer';
        if(state.focusSec!==sec)setAnno('hover','sec'+sec,()=>secAnchor(sec),oracleCard(ORC[sec],false),{hot:ORC[sec].state==='enforced'});else lingerClear('hover');return}}
    lingerClear('hover')}
}
// THE ORACLE CARD (UX-PLAN 9.3-9.7): its state, the switch kept apart from what it earned, the bar as a ladder of
// clauses (met lit, the first missing one amber and said in words), its history (demotions shown), and - focused -
// its calibration curve. The view never switches anything.
const STATE_WORD={enforced:'trusted',sampled:'trying out',shadow:'watching'};
const CLAUSE_WORD={rows:'enough examples',classes:'both right and wrong seen',minority:'enough wrong ones to learn from',auroc:'ranks its own errors',
  precision:'a sure-enough threshold',wilson:'sure even at worst',rows_above:'enough examples above that threshold',ece:'its confidence is honest',acting:'right when it acts'};
function secAnchor(sec){const th=(sec+.5)/NSEC*Math.PI*2+Math.PI/2;return project(new V3(Math.cos(th)*R*1.02,Math.sin(th)*R*1.02,0))}
function ladderHTML(o){if(!o.clauses)return '';const cl=o.clauses.filter(c=>!(c.id==='acting'&&c.met===null));
  const gap=cl.find(c=>c.id===o.first_missing);
  return `<div class="ladder">${cl.map(c=>`<i class="${c.met===true?'on':c.met===null?'na':c.id===o.first_missing?'gap':''}" title="${esc((CLAUSE_WORD[c.id]||c.id)+(c.words?' - '+c.words:''))}"></i>`).join('')}
    <span>${fmt(cl.filter(c=>c.met===true).length)} of ${fmt(cl.filter(c=>c.met!==null).length)} parts of the bar met</span></div>${gap?`<div class="m"><span class="gapw">${esc(gap.words||CLAUSE_WORD[gap.id]||gap.id)}</span></div>`:''}`}
function historyHTML(o){const h=(o.history||[]).slice(-4);if(h.length<2&&!(h[0]&&h[0].state!==o.state))return '';
  return `<div class="m">${h.map(x=>`${STATE_WORD[x.state]||x.state} ${new Date(x.at).toLocaleDateString('en-GB',{day:'numeric',month:'short'})}`).join(' → ')}</div>`}
function curveSVG(o){const k=o.curve;if(!k||k.length<2)return '';const W=150,H=64,X=v=>4+v*(W-8),Y=v=>H-4-v*(H-8);
  return `<svg class="curve" width="${W}" height="${H}"><path d="M${X(0)},${Y(0)}L${X(1)},${Y(1)}" class="diag"/><path d="${k.map((p,i)=>(i?'L':'M')+X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1)).join('')}" class="fit"/>${o.threshold!=null?`<path d="M${X(o.threshold)},${H-2}L${X(o.threshold)},${H-10}" class="notch"/>`:''}</svg><div class="m">how sure it says it is, against how often it is right${o.threshold!=null?` · it acts above ${Math.round(o.threshold*100)}%`:''}</div>`}
function oracleCard(o,deep){
  const measuring=o.consumer==='call_closing';
  const k=measuring?'measurement only':`${STATE_WORD[o.state]||'watching'}${o.job?' · '+esc(String(o.job).replace(/_/g,' ')):''}`;
  const doing=measuring?'it only measures; it never decides, by design':o.state==='enforced'?'it makes this decision itself now':o.state==='sampled'?'it decides now and then, while IRIS checks it':'it watches and learns; it does not act yet';
  return `<div class="k">${k}${o.owner_switch?' · <span class="u">switched on by you</span>':''}</div><div class="t">${esc(oracleWord(o.consumer))}</div>
    <div class="m">${doing}<br>learned from <em>${fmt(o.rows)}</em> examples</div>${measuring?'':ladderHTML(o)}${historyHTML(o)}${deep?curveSVG(o):'<span class="go">click · its ladder and its curve</span>'}`}
function focusSector(sec){state.focusSec=sec;if(sec<0){clearAnno('focus');return}
  if(slots.focus)slots.focus.key=null;setAnno('focus','secf'+sec,()=>secAnchor(sec),oracleCard(ORC[sec],true),{hot:true});clearAnno('hover')}
// THE HEALTH VIEW (UX-PLAN 7.5, key k): each territory tinted by how well its claims hold - cyan where they are proven,
// amber where they are still learning, red where they are contradicted - and one line of counts under the breadcrumb.
// Off: the territories' own colours come back. It reads only; it changes nothing.
const healthEl=document.createElement('div');healthEl.id='health';$('hud').appendChild(healthEl);
const regColOwn=SU.uRegCol.value.map(c=>c.clone());
function setHealth(on){state.health=on;
  REG.forEach((d,i)=>{const lms=M.landmarks.filter(l=>l.domain===d);const n=Math.max(1,lms.length);
    const pv=lms.filter(l=>l.tier!=='candidate').length/n,bad=lms.filter(l=>l.contradictions>0).length/n;
    if(!on){SU.uRegCol.value[i].copy(regColOwn[i]);return}
    SU.uRegCol.value[i].copy(new THREE.Color('#ffb547').lerp(new THREE.Color('#7fe8ff'),pv).lerp(new THREE.Color('#ff4a3d'),Math.min(1,bad*2)))});
  const L=M.landmarks,c=M.meta?.counts||{};
  healthEl.innerHTML=on?`health · <em>${fmt(L.filter(l=>l.tier!=='candidate').length)}</em> proven · <em>${fmt(L.filter(l=>l.tier==='candidate').length)}</em> still learning · <span class="w">${fmt(L.filter(l=>l.contradictions>0).length)} contradicted</span> · <em>${fmt(c.landmarks_absorbed||0)}</em> cleaned or merged in all<br><span class="dim">cyan holds · amber learning · red contradicted &nbsp; k · back to the territories' colours</span>`:'';
  healthEl.classList.toggle('on',on)}
function showMind(on){motes.forEach((m,i)=>{const n='mote'+i;if(on){setAnno(n,n+m.state,()=>project(m.pos),`<div class="m" style="color:${m.state==='in'?'#d4ecf6':'#33454f'}">${esc(m.label)}${m.state==='in'?'':' · set aside'}</div>`)}else clearAnno(n)});
  if(on)setAnno('mindk','mind',()=>{const c=project(new V3(0,-R*.2,0));return {x:c.x,y:c.y,front:true}},`<div class="k">on IRIS's mind right now</div>`);else clearAnno('mindk')}
canvas.addEventListener('pointermove',e=>{mouse.x=_px(e);mouse.y=_py(e);mouse.nx=_px(e)/innerWidth*2-1;mouse.ny=-(_py(e)/innerHeight*2-1);
  if(mouse.down&&e.buttons===0)mouse.down=false; // a lost pointerup must not turn hovering into dragging
  if(mouse.down){const dx=_px(e)-mouse.lx,dy=_py(e)-mouse.ly;mouse.dragged+=Math.abs(dx)+Math.abs(dy);mouse.lx=_px(e);mouse.ly=_py(e);cam.idle=0;
    if(cam.mode==='orbit'){cam.azT-=dx*.005;cam.elT=clamp(cam.elT+dy*.004,-1.2,1.2)}
    else if(cam.mode==='fly'){cam.yawT-=dx*.004;cam.pitchT=clamp(cam.pitchT+dy*.004,-1.4,1.4)}}
  else hover(_px(e),_py(e))});
tcv.addEventListener('pointermove',e=>{mouse.x=_px(e);mouse.y=_py(e);hover(_px(e),_py(e))});
canvas.addEventListener('pointerdown',e=>{mouse.down=true;mouse.dragged=0;mouse.lx=_px(e);mouse.ly=_py(e)});
addEventListener('pointerup',e=>{const was=mouse.down;mouse.down=false;if(!was||mouse.dragged>6)return;click(_px(e),_py(e))});
tcv.addEventListener('click',e=>{const x=_px(e),y=_py(e);
  const cr=crumbHit(x,y);if(cr){setTissueLevel(tissue.path.slice(0,cr.k),null);return}
  const i=tissueHit(x,y);
  if(i<0){const th=threadHit(x,y);if(th>=0){enterTunnel(tissue.threads[th].s);return}tissue.focus=-1;clearAnno('focus');return}
  const c=tissue.cells[i];
  if(c.type==='group'){setTissueLevel([...tissue.path,c.label],{x:c.cx,y:c.cy});return} // open a layer: it blooms out of the cell
  tissue.focus=tissue.focus===i?-1:i;clearAnno('hover');
  if(tissue.focus>=0){const s=M.sById.get(c.a.session);
    setAnno('focus','artf'+i,()=>({x:c.cx,y:c.cy,front:true}),`<div class="k">${KIND_WORD[c.a.kind]||c.a.kind} · ${esc(c.a.folder||'unsorted')} · made ${ago(c.a.ts)}</div><div class="t">${esc(c.a.name)}</div>
      <div class="m">${s?`made while: <em>${esc(s.objective)}</em>`:''}</div>${s?`<span class="go" data-go="${s.id}">→ step into that thread</span>`:''}`,{hot:true})}
  else clearAnno('focus')});
// a thread = one thought and everything linked to it in this session; scrolling then travels
// from one of its neurons to the next along the wall
function selectThread(li){if(!tunnel)return;tunnel.sel=li;tunnel.threadU.uSel.value=li;tunnel.threadU.uSelOn.value=li>=0?1:0;
  if(li<0){tunnel.stops=null;hint('scroll / w s · travel through the strand<br>hover · read a moment &nbsp; esc · back to the mind');return}
  const L_=tunnel.linked;const us=tunnel.stars.filter(s=>s.li===li||L_.has(li+'-'+s.li)||L_.has(s.li+'-'+li)).map(s=>s.u).sort((a,b)=>a-b);
  tunnel.stops=us.filter((u,i)=>!i||u-us[i-1]>.004);
  const next=tunnel.stops.find(u=>u>cam.tp+.01);if(next!=null)cam.tpT=Math.max(0,next-.02);cam.idle=-9;
  hint(`following one thread · ${tunnel.stops.length} linked claims<br>scroll · next / previous &nbsp; enter · open in the mind &nbsp; esc · let go`)}
// step to the previous / next neuron: along the selected thread, or along every neuron of the session
function neuronStep(dir){if(!tunnel)return;if(tunnel.stops)return threadStep(dir);
  const us=[...new Set(tunnel.stars.map(s=>s.u))].sort((a,b)=>a-b);const now=cam.tpT+.02;
  const u=dir>0?us.find(v=>v>now+.004):[...us].reverse().find(v=>v<now-.004);if(u!=null){cam.tpT=Math.max(0,u-.02);cam.idle=-9}}
function throughDoor(){if(!tunnel||state.doorLock)return;state.doorLock=true;setTimeout(()=>state.doorLock=false,1500);
  const nx=tunnel.door.next;if(nx)enterTunnel(nx);else exitTunnel()}
// WALKING (UX-PLAN 6.2). In the corridor Shift+← → steps turn to turn (each user message starts a turn) and Tab
// walks to the far doorway. On the helix ← → step strand to strand in time (the ones the chips keep) and show the
// same card a hover shows; ↑ ↓ move a day through time. The keyboard reuses the pointer's hover, so both read alike.
function turnStep(dir){if(!tunnel)return;const us=tunnel.items.filter(n=>n.type==='msg'&&n.m.role==='user').map(n=>n.u).sort((a,b)=>a-b);
  const now=cam.tpT+.02;const u=dir>0?us.find(v=>v>now+.004):[...us].reverse().find(v=>v<now-.004);if(u!=null){cam.tpT=Math.max(0,u-.02);cam.idle=-9}}
function toDoorway(){if(!tunnel)return;cam.tpT=Math.max(cam.tpT,.955);cam.idle=-9}
const beadOrder=()=>sess.map((s,i)=>i).filter(i=>bF[i]).sort((a,b)=>sess[a].started-sess[b].started);
function beadStep(dir){const order=beadOrder();if(!order.length)return;const at=order.indexOf(state.hoverBead);
  const k=order[at<0?(dir>0?0:order.length-1):clamp(at+dir,0,order.length-1)];const y=helixY(sessS(sess[k]));
  cam.targetT.y=clamp(y,-HELIX_H,HELIX_H);cam.idle=-9;
  setTimeout(()=>{const a=project(new V3(0,y,0));if(a.front)hover(a.x,a.y)},420)}   // the helix has turned to it: hover it
function dayStep(dir){const now=nowS();cam.targetT.y=clamp(cam.targetT.y+dir*Math.max(.05,Math.abs(timeY(now)-timeY(now-86400))),-HELIX_H,HELIX_H);cam.idle=-9}
function threadStep(dir){const st=tunnel.stops;if(!st||!st.length)return;const now=cam.tpT+.02;
  const u=dir>0?st.find(v=>v>now+.004):[...st].reverse().find(v=>v<now-.004);if(u!=null)cam.tpT=Math.max(0,u-.02);cam.idle=-9}
function openThreadInMind(){const li=tunnel?.sel;if(li==null||li<0)return;exitTunnel(()=>{const fi=LM[li].dom;
  dive(fi);const wait=setInterval(()=>{if(state.inside){clearInterval(wait);flyToSoma(li)}},120)})}
function click(x,y){
  if(cam.tween||state.diving)return;
  hover(x,y);
  if(cam.mode==='tunnel'&&tunnel){if(state.hoverStar>=0)selectThread(tunnel.stars[state.hoverStar].li);
    else if(state.hoverDoor==='door')throughDoor();else if(state.hoverDoor==='back'){selectThread(-1);cam.tpT=.012;cam.idle=-6}return}
  if(state.lens==='cortex'&&slots.hover?.on&&/^pin\d+$/.test(slots.hover.key||'')){focusPin(+slots.hover.key.slice(3));return}   // a pin: its card
  if(state.inside){if(state.hoverSoma>=0)flyToSoma(state.hoverSoma);else{setFocusSoma(-1);clearAnno('focus');satellites(-1);
      // click into open space: glide that way and turn toward it
      const d=new V3(x/innerWidth*2-1,-(y/innerHeight*2-1),.5).unproject(camera).sub(camera.position).normalize();
      cam.vel.addScaledVector(d,R*.9);cam.yawT=cam.yaw+angWrap(Math.atan2(d.x,d.z)-cam.yaw)*.6;cam.pitchT=lerp(cam.pitchT,Math.asin(clamp(d.y,-1,1)),.6);cam.idle=0}return}
  if(state.lens==='cortex'&&state.hoverReg>=0)dive(state.hoverReg);
  if(state.lens==='oracle'){focusSector(state.hoverSec>=0&&state.hoverSec!==state.focusSec?state.hoverSec:-1);return}
  if(state.lens==='timeline'){if(state.hoverTurn>=0){const t=TURNS[state.hoverTurn];enterTunnel(t.s);
      const w=setInterval(()=>{if(cam.mode!=='tunnel'||!tunnel||tunnel.session!==t.s)return;clearInterval(w);   // to the turn's own message
        const it=tunnel.items.find(n=>n.type==='msg'&&n.m.ts===t.user.ts);if(it){cam.tpT=Math.max(0,it.u-.02);cam.idle=-9}},150);setTimeout(()=>clearInterval(w),8000);return}
    if(state.hoverBead>=0)enterTunnel(sess[state.hoverBead]);else syncClick()}
}
canvas.addEventListener('wheel',e=>{e.preventDefault();cam.idle=0;
  if(cam.mode==='orbit'){if(state.lens==='timeline'&&e.ctrlKey){cam.distT=clamp(cam.distT*(1+e.deltaY*.0015),R*1.1,R*9)}   // turn zoom
    else if(state.lens==='timeline'){cam.targetT.y=clamp(cam.targetT.y-e.deltaY*.02,-HELIX_H,HELIX_H)}else cam.distT=clamp(cam.distT*(1+e.deltaY*.001),R*2.2,R*9)}
  else if(cam.mode==='fly'){cam.vel.addScaledVector(dirOf(cam.yaw+cam.lean.x,cam.pitch+cam.lean.y),-clamp(e.deltaY,-120,120)*.03)}
  else if(cam.mode==='tunnel'){if(tunnel?.stops){const n=performance.now();if(n-(state.lastStep||0)>380){state.lastStep=n;threadStep(Math.sign(e.deltaY))}}
    else{cam.tpT+=e.deltaY*.00012;if(cam.tp>.975&&e.deltaY>0)throughDoor()}}},{passive:false});
addEventListener('keydown',e=>{
  if(!_active)return;
  const _t=e.target;if(_t&&_t!==$('q')&&(_t.tagName==='INPUT'||_t.tagName==='TEXTAREA'||_t.tagName==='SELECT'||_t.isContentEditable))return; // typing elsewhere in the app
  if(document.activeElement===$('q')){if(e.key==='Escape'){closeSearch();e.preventDefault();e.stopPropagation()}if(e.key==='Enter'){goSearch()}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();selSearch(searchSel+(e.key==='ArrowDown'?1:-1))}return}
  dismissCoach();
  if(e.key==='?'){toggleHelp();e.preventDefault();return}
  if(e.key==='Escape'&&help.on){toggleHelp(false);e.preventDefault();e.stopPropagation();return}   // the sheet closes before anything steps out
  const k=e.key.toLowerCase();keys[k]=true;cam.idle=0;
  if(k==='enter'&&cam.mode==='tunnel'&&tunnel?.sel>=0){openThreadInMind();return}
  if(cam.mode==='tunnel'&&e.shiftKey&&(k==='arrowright'||k==='arrowleft')){turnStep(k==='arrowright'?1:-1);e.preventDefault();return}
  if(cam.mode==='tunnel'&&k==='tab'){toDoorway();e.preventDefault();return}
  if(cam.mode==='tunnel'&&!e.altKey&&(k==='arrowright'||k==='arrowleft')){neuronStep(k==='arrowright'?1:-1);return}
  if(state.lens==='timeline'&&cam.mode==='orbit'&&!e.altKey&&(k==='arrowright'||k==='arrowleft')){beadStep(k==='arrowright'?1:-1);e.preventDefault();return}
  if(state.lens==='timeline'&&cam.mode==='orbit'&&(k==='arrowup'||k==='arrowdown')){dayStep(k==='arrowup'?1:-1);e.preventDefault();return}
  // Escape (and Alt+Left, and the mouse's back button) steps out ONE level; only at the top level does it pass through
  // (the dashboard then closes as before). Enter goes in, to what the pointer is on.
  if(k==='escape'||(k==='arrowleft'&&e.altKey)){if(stepOut()){e.preventDefault();e.stopPropagation()}return}
  if(k==='enter'&&goIn()){e.preventDefault();return}
  if(['1','2','3','4'].includes(k)&&!e.ctrlKey)setLens(LENSES[+k-1][0]);
  if(k==='/'){e.preventDefault();openSearch()}
  if(k==='s'&&state.lens==='cortex'&&cam.mode==='orbit')state.showSpaces=!state.showSpaces;
  if(k==='k'&&state.lens==='cortex')setHealth(!state.health);
  if(k==='r'&&!e.ctrlKey&&!e.metaKey)replayTurn();
  if(k==='f'&&USE_REAL)setFollow(!follow.on);
  if(k==='g'&&SCRUB_LENS.has(state.lens)&&!state.inside&&cam.mode==='orbit'){state.scrub=0;state.scrubT=0;state.replay=true}
  if(k==='t'){themeIdx=(themeIdx+1)%THEMES.length;BRAND.set(THEMES[themeIdx][1]);document.documentElement.style.setProperty('--brand',THEMES[themeIdx][1]);
    coreHalo.material.color.copy(BRAND)}},true);
addEventListener('keyup',e=>{keys[e.key.toLowerCase()]=false});
// one level out, the innermost first: a followed thread, the corridor, a focused claim, the territory, a folder of things
// made, a kind singled out in the key, the recall arches of a strand. False at the top level (nothing to step out of).
function stepOut(){
  if(cam.tween||state.diving)return true;   // a flight is under way: swallow, never let the dashboard close mid-flight
  if(cam.mode==='tunnel'&&tunnel?.sel>=0){selectThread(-1);return true}
  if(cam.mode==='tunnel'){exitTunnel();return true}
  if(state.inside&&state.focusSoma>=0){setFocusSoma(-1);clearAnno('focus');satellites(-1);return true}
  if(state.inside){exitInterior();return true}
  if(state.lens==='artifacts'&&tissue.path.length){tissueUp();return true}
  if(keyFocus){setKindFocus(null);return true}
  if(state.lens==='timeline'&&sync.sid){disposeSync();clearAnno('hover');return true}
  if(state.lens==='oracle'&&state.focusSec>=0){focusSector(-1);return true}
  if(clearUses()){hint('');return true}
  return false}
// one level in, to what the pointer is on
function goIn(){
  if(cam.tween||state.diving)return false;
  if(cam.mode==='tunnel'&&tunnel?.sel>=0){openThreadInMind();return true}
  if(state.inside&&state.hoverSoma>=0){flyToSoma(state.hoverSoma);return true}
  if(state.lens==='cortex'&&!state.inside&&state.hoverReg>=0){dive(state.hoverReg);return true}
  if(state.lens==='timeline'&&state.hoverBead>=0){enterTunnel(sess[state.hoverBead]);return true}
  return false}
// the mouse's back button (button 3) is the same step out
canvas.addEventListener('mouseup',e=>{if(e.button===3&&_active){e.preventDefault();stepOut()}});
// FOCUS a thing from outside (a deep link, the chat): "claim:<id>", "strand:<id>" / "thread:<id>", "turn:<conv>:<turn>",
// "lens:<cortex|timeline|artifacts|oracle>". The view flies there the way a click would. False: not in this memory.
function focusRef(ref){
  const [kind,...rest]=String(ref||'').split(':');const id=rest.join(':');
  if(kind==='lens'&&LENSES.some(l=>l[0]===id)){setLens(id);return true}
  if(kind==='claim'){const k=M.lmIndex?.get(id);if(k==null)return false;
    const go=()=>{dive(LM[k].dom);const w=setInterval(()=>{if(state.inside){clearInterval(w);flyToSoma(k)}},120);setTimeout(()=>clearInterval(w),8000)};
    if(cam.mode==='tunnel')exitTunnel(go);else if(state.inside)exitInterior(go);else{setLens('cortex');setTimeout(go,300)}return true}
  if(kind==='strand'||kind==='thread'){const s_=M.sById?.get(id);if(!s_)return false;enterTunnel(s_);return true}
  const toTop=go=>{if(cam.mode==='tunnel')exitTunnel(go);else if(state.inside)exitInterior(go);else go()};
  if(kind==='artifact'){const a=M.artifacts.find(a=>a.id===id);if(!a)return false;
    toTop(()=>{setLens('artifacts');setTimeout(()=>{setTissueLevel([FORMAT_OF[a.kind]||'other',a.folder||'unsorted'],null);tissue.focus=tissue.cells.findIndex(c=>c.a===a)},1800)});return true}
  if(kind==='node'){if(!NDS.some(n=>n.id===id))return false;toTop(()=>{setLens('cortex');state.showSpaces=true});return true}
  if(kind==='pin'){const p=M.pins.find(p=>p.id===id),t=p?.refs?.find(r=>r.t==='thread'||r.t==='session');return t?focusRef('strand:'+t.id):false}
  // the episode's own strand when the memory knows the episode, else the id's prefix ("<conv>:<turn>")
  if(kind==='turn'){const ep=M.epById?.has(id)?id:rest.slice(1).join(':')||id;   // "<conv>:<turn>": the moments carry the turn id alone
    const conv=M.epById?.get(id)?.session||rest[0],s_=M.sById?.get(conv);if(!s_)return false;enterTunnel(s_);chatTurn={conv:s_.id,turn:ep};
    // once the corridor stands, travel to the turn's first moment
    const w=setInterval(()=>{if(cam.mode!=='tunnel'||!tunnel||tunnel.session!==s_)return;clearInterval(w);
      const it=tunnel.items.find(x=>x.type==='event'&&(x.e.episode===ep||x.e.episode===id));if(it){cam.tpT=Math.max(0,it.u-.02);cam.idle=-9}},150);
    setTimeout(()=>clearInterval(w),8000);return true}
  return false}
// THE TIME CURSOR (MEMORY-UX-PLAN §5.2): one date for every view, default now. The cortex shows the memory as it
// was (state.scrub feeds uScrub), the helix centres on that day, the artifacts dim what was made later. The
// breadcrumb says the date in amber while the cursor is in the past; one click on it returns to now.
// (cursorTs, cursorNow, SCRUB_LENS and scrubSeen live next to "state": the breadcrumb and the artifacts read them.)
const scrubEl=$('scrub');
function scrubFrom(e){const r=scrubEl.getBoundingClientRect();state.scrubT=state.scrub=clamp((e.clientX-r.left)/r.width,0,1);state.replay=false}
scrubEl.addEventListener('pointerdown',e=>{scrubEl.setPointerCapture(e.pointerId);scrubFrom(e);scrubEl.onpointermove=scrubFrom});
scrubEl.addEventListener('pointerup',()=>{scrubEl.onpointermove=null});
scrubEl.addEventListener('dblclick',()=>{state.scrubT=1});
// SEARCH (MEMORY-SURFACE-BUILD §3): text only, built for memory.db. On a real memory the backend answers
// (opts.search -> GET /api/memory/search: ranked by the memory's own law, never counted as a recall); the demo searches
// its own model. While the user moves through the results the scene previews WITHOUT moving the camera: the claims in
// the results light, everything else dims. Enter or a click flies to the chosen one; Esc closes.
let searchSeq=0,searchAbort=null,searchTimer=0,searchRes=[],searchSel=0;
const RESULT_WORD={claim:'claim',step:'step',moment:'moment',turn:'turn',pin:'pin',artifact:'made',node:'node',strand:'strand'};
function openSearch(){$('search').classList.add('on');host.classList.add('searching');$('q').value='';$('q').focus();runSearch('')}
function closeSearch(){$('search').classList.remove('on');host.classList.remove('searching');$('q').blur();state.search='';clearTimeout(searchTimer);searchAbort?.abort();searchSeq++;
  searchRes=[];forestU.uSearch.value=0;for(let j=0;j<NL;j++)somaData[j*8+2]=j===state.focusSoma?1:0;somaTex.needsUpdate=true;$('qres').innerHTML=''}
function lightClaims(ids){for(let j=0;j<NL;j++)somaData[j*8+2]=ids.has(j)?1:0;somaTex.needsUpdate=true;forestU.uSearch.value=state.search?1:0}
// the demo memory: the same answer shape from its own model (words AND, case-insensitive)
function localSearch(q){const words=q.toLowerCase().split(/\s+/).filter(Boolean),m=t=>words.every(w=>String(t||'').toLowerCase().includes(w));
  const all=[...LM.filter(l=>m(l.claim)).map(l=>({kind:'claim',id:l.id,title:l.claim,why:l.tier==='candidate'?'learning':'proven',ref:{claim:l.id}})),
    ...sess.filter(s=>m(s.objective)).map(s=>({kind:'strand',id:s.id,title:s.objective,why:ago(s.started),ref:{strand:s.id}})),
    ...M.artifacts.filter(a=>m(a.name)).map(a=>({kind:'artifact',id:a.id,title:a.name,why:a.kind,ref:{artifact:a.id}}))];
  const totals={},per={};all.forEach(x=>totals[x.kind]=(totals[x.kind]||0)+1);
  return {results:all.filter(x=>(per[x.kind]=(per[x.kind]||0)+1)<=8),totals,notes:[]}}
function runSearch(q){state.search=q.trim();clearTimeout(searchTimer);searchAbort?.abort();const seq=++searchSeq;
  if(!state.search){searchRes=[];lightClaims(new Set());renderSearch({notes:['type to find what IRIS remembers · try proven, failed, last week, in:<thread>']});return}
  if(!opts.search){showSearch(localSearch(state.search));return}
  $('qres').classList.add('busy');
  searchTimer=setTimeout(()=>{const ac=new AbortController();searchAbort=ac;
    opts.search(state.search,ac.signal).then(r=>{if(seq===searchSeq)showSearch(r)})
      .catch(e=>{if(seq!==searchSeq||ac.signal.aborted)return;searchRes=[];renderSearch({notes:[e?.message||'the memory did not answer']})})},160)}
function showSearch(r){searchRes=r.results||[];searchSel=0;const ids=new Set();
  for(const x of searchRes){const k=M.lmIndex.get(x.ref?.survivor||x.ref?.claim);if(k!=null)ids.add(k)}
  lightClaims(ids);renderSearch(r)}
function renderSearch(r){const el=$('qres');el.classList.remove('busy');
  const facets=(r.parse?.facets||[]).map(f=>`<b>${esc(f.text)}</b>`).join(' ');
  const total=Object.values(r.totals||{}).reduce((a,b)=>a+b,0)||searchRes.length;
  const head=searchRes.length?`${fmt(total)} found${total>searchRes.length?` · the first ${searchRes.length} · kind:claim (or step, turn …) shows more of one kind`:''} · ↑↓ enter`
    :(r.notes?.[0]||'nothing like that yet');
  el.innerHTML=`<span class="qh">${facets?facets+' · ':''}${esc(head)}</span>`+searchRes.map((x,i)=>
    `<a class="r${i===searchSel?' on':''}${x.ref?.ghost||x.ref?.cleaned?' gone':''}" data-i="${i}"><span class="kw">${RESULT_WORD[x.kind]||esc(x.kind)}</span>`+
    `<span class="tt">${esc(x.title||'')}</span><span class="why">${esc(x.why||'')}</span></a>`).join('')}
function selSearch(i){if(!searchRes.length)return;searchSel=(i+searchRes.length)%searchRes.length;
  $('qres').querySelectorAll('.r').forEach((a,j)=>a.classList.toggle('on',j===searchSel));$('qres').querySelector('.r.on')?.scrollIntoView({block:'nearest'})}
// a result's places to fly to, the most exact first (a cleaned claim goes to the claim it was merged into)
function refsOf(x){const r=x.ref||{},out=[];
  if(r.claim)out.push('claim:'+(r.survivor||r.claim));
  if(x.kind==='turn'&&(r.episode||r.turn))out.push('turn:'+(r.episode||r.turn));
  if(x.kind==='moment'&&r.turn)out.push('turn:'+r.turn);
  if(r.artifact)out.push('artifact:'+r.artifact);
  if(r.node)out.push('node:'+r.node);
  if(r.pin)out.push('pin:'+r.pin);
  if(r.strand)out.push('strand:'+r.strand);
  return out}
function goSearch(){const x=searchRes[searchSel];if(!x)return;
  if(refsOf(x).some(f=>focusRef(f))){closeSearch();return}
  $('qres').querySelector('.qh').textContent=x.ref?.ghost?'that strand was deleted - its memory remains, but it has no place on the timeline'
    :'that is in the memory but older than this view holds'}
$('q').addEventListener('input',e=>runSearch(e.target.value));
$('qres').addEventListener('pointermove',e=>{const a=e.target.closest('.r');if(a&&+a.dataset.i!==searchSel)selSearch(+a.dataset.i)});
$('qres').addEventListener('click',e=>{const a=e.target.closest('.r');if(a){selSearch(+a.dataset.i);goSearch()}});
const _onResize=()=>{innerWidth=host.clientWidth||1;innerHeight=host.clientHeight||1;pinH.value=innerHeight*.5;arborRes.value.set(innerWidth,innerHeight);renderer.setSize(innerWidth,innerHeight);composer.setSize(innerWidth,innerHeight);camera.aspect=innerWidth/innerHeight;
  camera.updateProjectionMatrix();if(state.lens==='artifacts')layoutTissue(false)};
const _ro=new ResizeObserver(()=>_onResize());_ro.observe(host);_cleanups.push(()=>_ro.disconnect());

// ═══════════════════════════════════════════════════════════════════════════
// 14. the frame
// ═══════════════════════════════════════════════════════════════════════════
initTissue();
camera.position.set(0,R*1.2,R*6);cam.look.set(0,0,0);
setLens('cortex');
ORC.forEach((o,i)=>{skinMat.uniforms.uSecProg.value[i]=barProgress(o);skinMat.uniforms.uSecState.value[i]=STATE_RANK[o.state]??0});
{const d=new Date(T0*1000);$('scrub').querySelector('.lbl0').textContent=d.toLocaleDateString('en-GB',{day:'numeric',month:'short'})}
// the ticker's first lines: on a real memory the two newest REAL moments, each saying when it happened; the demo opens on a sample
if(USE_REAL){const last=[...M.events].filter(e=>e.ts).sort((a,b)=>a.ts-b.ts).slice(-2);last.forEach(e=>tick({...e,_past:true}))}
else tick({family:'memory',label:'RECALL_DELIVERED',actor:'agent',evidence:'claim',valence:'neutral'});
let fpsAcc=0,fpsN=0,fps=60,statT=0,slowFrames=0;
const _frame=()=>{
  const dt=Math.min(clock.getDelta(),.1),t=clock.elapsedTime; // flights keep real time on slow frames
  U.uTime.value=t;
  simulate(dt);
  // Caducean breath: expand / compress (x) and attention (u) set the inner rhythm
  const sx=Math.sin(t*.13)+.4*Math.sin(t*.31),su=.5+.5*Math.sin(t*.07);
  // morph the organism
  const mk=1-Math.pow(.25,dt);for(const k of ['h','i','c']){const d=state.morphT[k]-state.morph[k];state.morph[k]+=clamp(d,-dt*.62,dt*.62)}
  skinMat.uniforms.uMH.value=state.morph.h;skinMat.uniforms.uMI.value=state.morph.i;skinMat.uniforms.uMC.value=state.morph.c;
  for(const k in state.vis)state.vis[k]=lerp(state.vis[k],state.visT[k],1-Math.pow(.08,dt));
  forestU.uVis.value=state.vis.forest;forestU.uNear.value=state.insideK||0;mistMat.uniforms.uMist.value=1-(state.insideK||0)*.75;wireMat.uniforms.uVis.value=state.vis.wire*(1-state.morph.h)*(1-state.morph.i)*(1-(state.insideK||0)*.7);   // from inside, the shell's long lines would cross the whole view
  xurMat.uniforms.uVis.value=state.vis.xur;beadMat.uniforms.uVis.value=state.vis.beads;rings.forEach(r=>r.material.uniforms.uVis.value=state.vis.rings*(1-(state.insideK||0)));
  forestU.uFocusDim.value=lerp(forestU.uFocusDim.value,state.focusDimT,1-Math.pow(.1,dt));
  // aperture
  const op=skinMat.uniforms.uOpen;op.value=lerp(op.value,state.openT,1-Math.pow(.02,dt));skinMat.uniforms.uOpenReg.value=op.value>.005||state.openT>0?state.diveReg:-1;
  // region activity decays to its base
  for(let i=0;i<REG.length;i++){regAct[i]=lerp(regAct[i],regBase[i],1-Math.pow(.3,dt));SU.uRegAct.value[i]=regAct[i]}
  SUB.forEach((s,j)=>{SU.uRegAct.value[NROOT+j]=regAct[s.ri]});
  // immune amplitudes only ever decay toward 0: a tightening lasts about a second, a relaxation a few; no build-up
  for(let i=0;i<NROOT;i++){if(IMM[i]===0)continue;IMM[i]*=Math.exp(-dt/(IMM[i]>0?1.3:3.4));if(Math.abs(IMM[i])<.004)IMM[i]=0}
  if(pinArtTethers)pinArtTethers.visible=state.lens==='artifacts';
  for(const l of pinTethers)l.material.opacity=state.vis.forest; // tethers fade with the rest of the cortex when another lens is up
  updateMarks(t);spaceU.uShow.value=lerp(spaceU.uShow.value,state.showSpaces&&state.lens==='cortex'?1:0,1-Math.pow(.02,dt));
  state.warn=Math.max(0,state.warn-dt*.8);skinMat.uniforms.uWarn.value=wireMat.uniforms.uWarn.value=state.warn;
  // shockwave (a user's word is the strongest thing on screen)
  const sh=shockAt(t);skinMat.uniforms.uShock.value=wireMat.uniforms.uShock.value=sh*.6;const b=bounceAt(t);
  skinMat.uniforms.uBounce.value=b;wire.scale.setScalar(b);
  if(sh>.001){const d=t-shockT;shockMesh.scale.setScalar(Math.max(.01,1+d/1.2*2.5));shockMat.opacity=Math.max(0,1-d/1.2*2.2)*.5;shockMesh.lookAt(camera.position)}else{shockMesh.visible=false}
  // soma state decay; promotions grow their dendrites outward
  let dirty=false;for(let k=0;k<NL;k++){const o=k*8;if(somaData[o]>0){somaData[o]=Math.max(0,somaData[o]-dt*.12);dirty=true}
    if(somaData[o+1]>0){somaData[o+1]=Math.max(0,somaData[o+1]-dt*.6);dirty=true}if(somaData[o+4]>0){somaData[o+4]=Math.max(0,somaData[o+4]-dt*.5);dirty=true}}
  if(state.grow){state.grow=state.grow.filter(k=>{somaData[k*8+3]=Math.min(1,somaData[k*8+3]+dt*.35);dirty=true;return somaData[k*8+3]<1})}
  if(dirty)somaTex.needsUpdate=true;
  // time scrub / growth replay
  if(state.replay){state.scrubT=Math.min(1,state.scrubT+dt/14);if(state.scrubT>=1)state.replay=false}
  state.scrub=lerp(state.scrub,state.scrubT,1-Math.pow(.02,dt));forestU.uScrub.value=state.scrub;
  scrubEl.classList.toggle('on',SCRUB_LENS.has(state.lens)&&cam.mode==='orbit'&&!state.diving&&!state.inside);
  // the helix follows the cursor when the cursor moves (a drag, "watch it grow", the return to now)
  if(state.lens==='timeline'&&cam.mode==='orbit'&&!cam.tween&&Math.abs(state.scrubT-scrubSeen)>.0005){
    scrubSeen=state.scrubT;cam.targetT.y=clamp(timeY(T0+(nowS()-T0)*state.scrubT),-HELIX_H,HELIX_H)}
  scrubEl.querySelector('.fill').style.width=(state.scrub*100)+'%';
  scrubEl.querySelector('.lbl').textContent=state.scrub>.995?'now':'as of '+new Date((T0+(nowS()-T0)*state.scrub)*1000).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
  // core, pupil, inner XurOrb shells
  state.pupil=lerp(state.pupil,state.pupilT,1-Math.pow(.05,dt));state.pupilT=lerp(state.pupilT,1,dt*.4);
  const pupilS=state.morph.i>.5?state.pupil*1.25:1;
  // in the iris the core becomes the pupil: dark, with a bright rim that dilates on each decision
  // dims by where the camera IS, so the core never flares while a flight passes through the skin
  const camR=camera.position.length()/R;
  state.insideK=lerp(state.insideK||0,cortex.visible?clamp((1.6-camR)/.7,0,1):0,1-Math.pow(.02,dt));
  core.scale.setScalar((1+sx*.06)*b*pupilS);coreMat.uniforms.uGain.value=.6*state.vis.core*(1-state.morph.i*.6)*(1-state.insideK*.55);
  coreHalo.material.opacity=(.08+.04*sx+(state.hoverCore?.16:0))*state.vis.core*(1-state.morph.i*.8)*(1-state.insideK*.85);
  cells.scale.setScalar(b);coreHalo.scale.setScalar(R*(1.0+.1*sx)*pupilS);
  for(let i=0;i<MAXSEC;i++){state.secPulse[i]=Math.max(0,state.secPulse[i]-dt*.7);skinMat.uniforms.uSecPulse.value[i]=state.secPulse[i]}
  {let o=0;const det=.52+.48*(.5+.5*Math.sin(t/4.2*Math.PI*2));const flat=state.morph.i;
    const v=xurV,S=xurS,C=xurC,qt=xurQt;
    for(let i=tendrils.length-1;i>=0;i--)if(t-tendrils[i].t0>4.2)tendrils.splice(i,1);
    XUR.forEach((sh,si)=>{xurPhase[si]+=dt*(Math.PI*2/28)*sh.speed*(1+su*1.4)*(REDUCED?.3:1);
      // tumble: each shell turns on its own axis (stopped and flattened when the iris forms)
      qt.setFromAxisAngle(xurSpin[si],t*.05*sh.speed*(1-flat)).premultiply(xurQ[si]).slerp(xurFlat,flat);
      // fills the interior (outer lobes graze the skin); shrinks to the collarette when the iris forms
      const sc=R*lerp(.78,.33,flat)*sh.scale*(1+sx*.05);
      const td=tendrils.filter(d=>d.si===si);
      for(let k=0;k<sh.n;k++){const j=Math.floor(k/XTUBE);const tt=j/sh.count*Math.PI*2+xurPhase[si];const [x,y]=curvePoint(tt,det);
        const lift=(1+.14*Math.cos(9*tt));
        v.set(x*sc*lift,y*sc*lift,sc*det*.3*Math.sin(9*tt+si*2.1)*(1-flat)+flat*R*.12);
        const oi=(o+k)*3,tub=sc*.035*(1-flat*.6);v.x+=xurOff[oi]*tub;v.y+=xurOff[oi+1]*tub;v.z+=xurOff[oi+2]*tub;
        v.applyQuaternion(qt);
        let a=sh.alpha*(.35+.65*(j/sh.count))*lerp(.42,.7,flat);
        for(const d of td){let dj=j-d.j0;if(dj<0)dj+=sh.count;if(dj>=d.n)continue;
          const u=(t-d.t0-dj*.012)/3.4;if(u<=0||u>=1)continue;const w=Math.sin(u*Math.PI);
          S.copy(somaPos[d.k]);C.addVectors(v,S).multiplyScalar(.5).addScaledVector(v,.35);
          const e=easeIO(w);bez(v,C,S,e,v);v.x+=xurOff[oi]*R*.012*w;v.y+=xurOff[oi+1]*R*.012*w;v.z+=xurOff[oi+2]*R*.012*w;a=Math.min(1,a+w*.6)}
        xurPos[oi]=v.x;xurPos[oi+1]=v.y;xurPos[oi+2]=v.z;xurA[o+k]=a}
      o+=sh.n})}
  xurGeo.attributes.position.needsUpdate=xurGeo.attributes.aA.needsUpdate=true;
  rings.forEach(r=>r.rotateZ(dt*.4*r.userData.sp*(.6+su)));
  // motes
  motes.forEach((m,i)=>{m.r=lerp(m.r,m.rT,1-Math.pow(.4,dt));m.ang+=dt*m.speed;const v=new V3(Math.cos(m.ang),Math.sin(m.ang),0).multiplyScalar(m.r).applyAxisAngle(m.axis,.9);
    m.pos.copy(v);moteP.set([v.x,v.y,v.z],i*3);moteA[i]=(m.state==='in'?.9:.25)*(1-state.morph.h)*(1-state.morph.i)});
  moteGeo.attributes.position.needsUpdate=moteGeo.attributes.aA.needsUpdate=true;
  // impulses
  updateSparks(dt);updateRings(dt);updateThreads(dt);updateSatellites(t);
  updateCamera(dt);syncFrame(dt);updateCrumb();$('key').classList.toggle('on',state.lens==='cortex'&&cam.mode!=='tunnel'&&!state.diving);
  $('chips').classList.toggle('on',state.lens==='timeline'&&cam.mode==='orbit'&&CHIP_GROUPS.length>0);
  if(cam.mode==='tunnel'&&tunnel){
    // the far doorway opens as you near the end of the thread; the side door stays ajar
    tunnel.door.mesh.material.uniforms.uOpen.value=smooth01((cam.tp-.78)/.18);
    tunnel.back.mesh.material.uniforms.uOpen.value=state.hoverDoor==='back'?.85:.5;
    rail.update(cam.tp);
    // arriving at a neuron names it, without a hover
    const here=cam.tp+.025;let best=-1,bd=.009;tunnel.stars.forEach((s,i)=>{const d=Math.abs(s.u-here);if(d<bd){bd=d;best=i}});
    if(best>=0&&!slots.hover?.on){const s=tunnel.stars[best];
      setAnno('arrive','arr'+best,()=>project(s.world),`<div class="k">claim · ${tunnel.sel===s.li?'on your thread':'in this strand'}</div><div class="t">${esc(LM[s.li].claim)}</div>`)}
    else if(best<0)clearAnno('arrive');
    // near the end the two doorways name themselves: the next thread ahead, the way back on the side
    if(cam.tp>.86){const nx=tunnel.door.next;
      setAnno('doorA','dA'+(nx?nx.id:'home'),()=>project(tunnel.door.world.clone().add(new V3(0,4,0))),
        `<div class="k">doorway · ahead</div><div class="t">${nx?esc(nx.objective):'back to the timeline'}</div><span class="go" ${nx?`data-go="${nx.id}"`:'data-home="1"'}>${nx?'step through to the next strand of this thread':'the last strand of its thread · return'}</span>`);
      setAnno('doorB','dB',()=>project(tunnel.back.world),`<div class="k">doorway · beside you</div><span class="go" data-rewind="1">↺ back to the beginning of this thread</span>`)}
    else{clearAnno('doorA');clearAnno('doorB')}}
  else{clearAnno('arrive');clearAnno('doorA');clearAnno('doorB')}
  // HUD
  placeRegionLabels(state.lens==='cortex'&&cam.mode==='orbit'&&!cam.tween&&!state.diving&&!state.showSpaces&&(state.hoverReg>=0||cam.idle<1.5&&mouse.x>0));
  placeSpaceLabels(state.showSpaces&&state.lens==='cortex'&&cam.mode==='orbit'&&!cam.tween&&!state.diving);
  placeAnnos();
  placeJobLabels(state.lens==='oracle'&&cam.mode==='orbit'&&!cam.tween);
  placeInsideLabels(state.inside&&!state.diving&&cam.mode==='fly');
  placeTimelineLabels(state.lens==='timeline'&&cam.mode==='orbit'&&!cam.tween&&!sync.sid);
  state.turnZoom=state.lens==='timeline'&&cam.mode==='orbit'&&camera.position.distanceTo(cam.look)<R*2.6;turnPts.visible=state.turnZoom;
  {const age=clock.elapsedTime-pupilLive.t;   // up in .35 s, held, back to turning by 3 s
    PU.uDec.value=age<.35?age/.35:age<2.2?1:Math.max(0,1-(age-2.2)/.8);
    PU.uVis.value=state.morph.i*(1-(state.insideK||0));PU.uDil.value=lerp(PU.uDil.value,1+.22*PU.uDec.value,1-Math.pow(.02,dt))}
  drawLiveDecision();
  drawTissue(dt);
  clearAnno('decision');   // the decision line is drawn under the arc ring by drawLiveDecision
  bloom.strength=.85-state.insideK*.35+sh*.8;
  // keep the drawing buffer the size of the window (emulated viewports do not always fire resize)
  if(Math.abs(renderer.domElement.width-Math.floor(innerWidth*DPR))>2||Math.abs(renderer.domElement.height-Math.floor(innerHeight*DPR))>2){
    renderer.setSize(innerWidth,innerHeight);composer.setSize(innerWidth,innerHeight);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix()}
  composer.render();
  // frame budget: the GPU is shared with local models
  fpsAcc+=dt;fpsN++;if(fpsAcc>1){fps=fpsN/fpsAcc;fpsAcc=0;fpsN=0;
  }
  statT-=dt;if(statT<=0){statT=1;updateStats(fps)}
};

// ── the host's controls ─────────────────────────────────────────────────────────────────────────
// THE FRAME GOVERNOR. The surface shares the page with the whole app (the chat, the dashboard): a Memory frame must
// never starve it. Measured 2026-10-21 in a software-WebGL pane: the app fell from 56 to 16 fps with Memory open, while
// the JavaScript of a frame took only ~1.6 ms - the cost is the GPU's drawing, visible only as a longer interval between
// animation frames. So the governor watches the PAGE's frame interval (every callback, drawn or skipped): below ~40 fps
// it gives up FRAMES first (the cap 30 -> 15), and sharpness last. A lower render resolution blurs the 1-pixel lattice
// and makes the cortex look sketched (owner, 2026-10-21: "faded … like lines from a scratchpad"), so the resolution
// floor is the full resolution while Memory has the spotlight (it is what the user is looking at) and 0.85 otherwise.
const _BASE_DPR = DPR;
let _minDpr = _BASE_DPR, _capFps = 30, _maxFps = 30, _lastDraw = 0, _lastTick = 0, _gap = 16, _n = 0;
const _setDpr = (d) => { DPR = d; renderer.setPixelRatio(DPR); composer.setPixelRatio?.(DPR); U.uPix.value = DPR; };
const _governed = () => {
  const now = performance.now();
  if (_lastTick) _gap = _gap * 0.92 + Math.min(250, now - _lastTick) * 0.08;
  _lastTick = now;
  if (++_n % 40 === 0) {
    if (_gap > 25) {
      if (_maxFps > 15) _maxFps = Math.max(15, _maxFps - 5);
      else if (DPR > _minDpr + 0.01) _setDpr(Math.max(_minDpr, DPR * 0.9));
    } else if (_gap < 18) {
      if (DPR < _BASE_DPR - 0.01) _setDpr(Math.min(_BASE_DPR, DPR / 0.9));
      else if (_maxFps < _capFps) _maxFps = Math.min(_capFps, _maxFps + 5);
    }
  }
  if (DPR < _minDpr - 0.01) _setDpr(_minDpr);   // the floor rose (the spotlight came back): sharp again at once
  if (now - _lastDraw < 1000 / _maxFps - 1.5) return;
  _lastDraw = now;
  _frame();
};
let _running = false;
const resume = () => { if (_running) return; _running = true; clock.getDelta(); renderer.setAnimationLoop(_governed); };
const pause = () => { if (!_running) return; _running = false; renderer.setAnimationLoop(null); };
canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); pause(); opts.onError?.(new Error('webgl context lost')); });
resume();
return {
  setActive(a) { _active = !!a; },
  /** Fly to a thing: "claim:<id>", "strand:<id>", "thread:<id>", "turn:<conv>:<turn>", "lens:<name>". False: not in this memory. */
  focus(ref) { try { return focusRef(ref); } catch (e) { console.warn('[memory] focus failed', ref, e); return false; } },
  /** A live tap message from the backend ({type, payload}: memory_event, landmark_update, oracle_decision). */
  live(msg) { try { liveMsg(msg); } catch (e) { console.warn('[memory] live message failed', msg?.type, e); } },
  /** Memory is what the user looks at (spotlit, detached): never trade its sharpness for frames. */
  setFocus(f) { _minDpr = f ? _BASE_DPR : Math.min(_BASE_DPR, 0.85); },
  /** The governor's state (development): frame cost, frame cap, resolution. */
  stats() { return { pageFps: Math.round(1000 / _gap), maxFps: _maxFps, dpr: Math.round(DPR * 100) / 100 }; },
  pause, resume,
  dispose() {
    pause();
    for (const f of _cleanups.splice(0)) { try { f(); } catch {} }
    scene.traverse((o) => { o.geometry?.dispose?.(); const m = o.material; if (Array.isArray(m)) m.forEach((x) => x.dispose?.()); else m?.dispose?.(); });
    composer.dispose?.(); renderer.dispose(); renderer.forceContextLoss?.();
    host.innerHTML = ''; host.classList.remove('iris-memory', 'searching');
  },
  debug: __cortex,
};
}
