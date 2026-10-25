// The Memory surface's stylesheet and HUD markup, ported verbatim from the validated mockup
// (docs/Design/Memory-Cortex/index.html). Every selector is scoped to .iris-memory and nothing is
// position:fixed, so the surface lives inside the dashboard wing like any other surface.
export const MEMORY_CSS = String.raw`
.iris-memory{
  --bg:#020306; --ink:#d4ecf6; --dim:#6c8796; --faint:#33454f; --brand:#00d4ff;
  --warn:#ff4a3d; --amber:#ffb547; --white:#f4fbff;
}
.iris-memory *{box-sizing:border-box}
.iris-memory{position:relative;margin:0;width:100%;height:100%;background:var(--bg);overflow:hidden;color:var(--ink);
  font-family:'JetBrains Mono',ui-monospace,monospace;-webkit-font-smoothing:antialiased}
.iris-memory canvas#gl{position:absolute;inset:0;display:block;width:100%;height:100%}
.iris-memory canvas#tissue{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;opacity:0;transition:opacity .5s}
.iris-memory canvas#tissue.on{pointer-events:auto;opacity:1}
.iris-memory #vignette{position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(ellipse at center,transparent 45%,rgba(0,0,0,.55) 85%,rgba(0,0,0,.9) 100%)}
.iris-memory svg#leaders{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
.iris-memory svg#leaders path{fill:none;stroke:rgba(212,236,246,.38);stroke-width:1}
.iris-memory svg#leaders path.hot{stroke:rgba(244,251,255,.8)}
.iris-memory #labels,.iris-memory #annos{position:absolute;inset:0;pointer-events:none}
.iris-memory .rlabel{position:absolute;white-space:nowrap;font-size:11px;letter-spacing:.04em;color:var(--dim);
  transition:opacity .35s,color .25s;opacity:0}
.iris-memory .rlabel b{font-weight:600;color:var(--ink);margin-right:.6em}
.iris-memory .rlabel i{display:block;font-style:normal;font-size:10px;color:var(--faint);line-height:1.5}
.iris-memory .syncr{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;letter-spacing:.06em;white-space:nowrap}
.iris-memory .sync{display:inline-block;width:42px;height:3px;margin:0 .5em;vertical-align:middle;background:rgba(212,236,246,.14)}.iris-memory .sync i{display:block;height:100%;background:currentColor}
.iris-memory .rlabel.hot b{color:var(--white)} .iris-memory .rlabel.hot i{color:var(--dim)}
.iris-memory .rlabel i.knows{display:none} .iris-memory .rlabel.hot i.knows{display:block;color:var(--ink)}
.iris-memory .anno{position:absolute;max-width:360px;pointer-events:none;opacity:0;transition:opacity .3s}
.iris-memory .anno.on{opacity:1}
.iris-memory .anno .k{font-size:10px;letter-spacing:.14em;text-transform:lowercase;color:#9cb6c3}
.iris-memory .anno .t{font-family:'Inter Tight',sans-serif;font-weight:400;font-size:19px;line-height:1.3;
  color:var(--white);margin:.35em 0 .5em}
.iris-memory .anno .m{font-size:10.5px;line-height:1.75;color:#b3c9d4}
.iris-memory /* leader-line labels float on the scene: a dark halo behind each glyph keeps them readable */
.anno:not(.cell){text-shadow:0 0 3px #000,0 0 8px #000,0 0 16px rgba(0,0,0,.9)}
.iris-memory /* cell: the point swells into an organic cell with the full text inside (artifact-cell language) */
.anno.cell{max-width:none;width:330px;padding:46px 44px 48px;text-align:center;
  background:radial-gradient(ellipse at 50% 42%,rgba(9,20,30,.96),rgba(3,8,14,.93) 72%);
  border:1px solid var(--cell,#7fe8ff);
  box-shadow:inset 0 0 22px -6px var(--cell,#7fe8ff),0 0 26px -6px var(--cell,#7fe8ff),0 0 70px -24px var(--cell,#7fe8ff);
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
  border-radius:47% 53% 44% 56% / 55% 45% 55% 45%;
  transform:scale(.04);opacity:0;transition:transform .55s cubic-bezier(.2,.9,.25,1.12),opacity .22s;
  animation:membrane 7s ease-in-out infinite alternate}
.iris-memory .anno.cell.on{transform:scale(1);opacity:1}
.iris-memory .anno.cell .k{color:var(--cell,#7fe8ff)}
.iris-memory .anno.cell .t{font-size:17.5px;color:#fff;margin:.45em 0 .6em}
.iris-memory .anno.cell .m{font-size:11px;color:#c3d6df}
.iris-memory .anno.cell .go{margin-top:.9em}
@keyframes membrane{0%{border-radius:47% 53% 44% 56%/55% 45% 55% 45%}50%{border-radius:55% 45% 52% 48%/46% 56% 44% 54%}
  100%{border-radius:44% 56% 49% 51%/52% 48% 57% 43%}}
@media (prefers-reduced-motion:reduce){.iris-memory .anno.cell{animation:none;transition:opacity .2s}}
.iris-memory .anno .m em{font-style:normal;color:var(--ink)}
.iris-memory .anno .m .w{color:var(--warn)} .iris-memory .anno .m .u{color:var(--white)}
.iris-memory .anno .go{display:inline-block;margin-top:.6em;font-size:10.5px;color:var(--brand);pointer-events:auto;cursor:pointer}
.iris-memory .anno .go:hover{color:var(--white)}
.iris-memory .anno.right{text-align:left} .iris-memory .anno.left{text-align:right}
.iris-memory #hud{position:absolute;inset:0;pointer-events:none}
.iris-memory #brand{position:absolute;left:22px;top:18px;font-size:11px;letter-spacing:.32em;color:var(--ink)}
.iris-memory #brand span{color:var(--dim)}
.iris-memory #local{position:absolute;left:22px;top:36px;font-size:10px;color:var(--faint);letter-spacing:.06em}
.iris-memory #crumb{position:absolute;left:22px;top:52px;font-size:10px;letter-spacing:.14em;color:var(--faint);white-space:nowrap;max-width:60vw;overflow:hidden;text-overflow:ellipsis}
.iris-memory #crumb b{font-weight:400;color:var(--dim)}.iris-memory #crumb .when{display:block;width:max-content;margin-top:6px;color:var(--amber);cursor:pointer;pointer-events:auto}.iris-memory #crumb .when:hover{color:var(--white)}.iris-memory #crumb i{font-style:normal;margin:0 .7em;opacity:.6}
.iris-memory .corner{position:absolute;width:18px;height:18px;border:0 solid rgba(212,236,246,.2)}
.iris-memory .corner.tl{left:10px;top:10px;border-left-width:1px;border-top-width:1px}.iris-memory .corner.tr{right:10px;top:10px;border-right-width:1px;border-top-width:1px}
.iris-memory .corner.bl{left:10px;bottom:10px;border-left-width:1px;border-bottom-width:1px}.iris-memory .corner.br{right:10px;bottom:10px;border-right-width:1px;border-bottom-width:1px}
.iris-memory #stats{position:absolute;right:22px;top:18px;font-size:10px;color:var(--faint);text-align:right;line-height:1.7}
.iris-memory #stats em{font-style:normal;color:var(--dim)}
.iris-memory #title{position:absolute;left:22px;top:70px;max-width:520px;font-family:'Inter Tight',sans-serif;
  font-weight:300;font-size:24px;line-height:1.25;color:var(--white);opacity:0;transition:opacity .6s}
.iris-memory #title small{display:block;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--dim);margin-top:.6em;letter-spacing:.04em}
.iris-memory #ticker{position:absolute;left:22px;bottom:22px;font-size:11px;line-height:1.8;max-width:46vw}
.iris-memory #ticker .line{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:opacity .6s}
.iris-memory #ticker .line.old{opacity:.32}
.iris-memory #follow{position:absolute;left:22px;bottom:66px;font-size:9.5px;letter-spacing:.08em;color:var(--faint);cursor:pointer;pointer-events:auto;user-select:none}
.iris-memory .anno .acts{margin-top:8px;font-size:10px;letter-spacing:.06em;color:var(--faint);pointer-events:auto}
.iris-memory .anno .acts a{color:var(--dim);cursor:pointer}.iris-memory .anno .acts a:hover{color:var(--white)}
.iris-memory #mine{position:absolute;left:22px;bottom:84px;font-size:9.5px;letter-spacing:.08em;color:var(--faint);max-width:min(420px,46vw);pointer-events:auto}
.iris-memory #mine .head{cursor:pointer}.iris-memory #mine .head:hover{color:var(--dim)}
.iris-memory #mine .list{margin-bottom:6px;max-height:40vh;overflow:auto}
.iris-memory #mine .row{padding:4px 0;border-top:1px solid rgba(212,236,246,.06);line-height:1.5}.iris-memory #mine .row.gone{opacity:.45}
.iris-memory #mine .row .t{color:var(--dim)}.iris-memory #mine a[data-undo-id],.iris-memory #mine a[data-claim]{color:var(--brand);cursor:pointer}
.iris-memory .rlabel.job{font-size:9px;letter-spacing:.18em;text-transform:lowercase;color:var(--faint);transition:opacity .4s}
.iris-memory .anno .ladder{margin-top:7px;font-size:9.5px;color:var(--faint)}.iris-memory .anno .ladder i{display:inline-block;width:6px;height:6px;margin-right:4px;border-radius:50%;border:1px solid rgba(212,236,246,.35)}
.iris-memory .anno .ladder i.on{background:var(--brand);border-color:var(--brand)}.iris-memory .anno .ladder i.gap{background:var(--amber);border-color:var(--amber);box-shadow:0 0 6px var(--amber)}.iris-memory .anno .ladder i.na{opacity:.25}
.iris-memory .anno .ladder span{margin-left:4px}
.iris-memory .anno svg.curve{display:block;margin-top:8px}.iris-memory .anno svg.curve path{fill:none}.iris-memory .anno svg.curve .diag{stroke:rgba(212,236,246,.15);stroke-dasharray:2 3}
.iris-memory .anno svg.curve .fit{stroke:var(--brand);stroke-width:1.2}.iris-memory .anno svg.curve .notch{stroke:var(--amber);stroke-width:1.5}
.iris-memory #orcline{position:absolute;transform:translateX(-50%);text-align:center;font-size:10.5px;line-height:1.7;letter-spacing:.04em;color:var(--dim);pointer-events:none;white-space:nowrap;opacity:0;text-shadow:0 0 8px #020306}
.iris-memory #orcline em{font-style:normal;color:var(--ink)}
.iris-memory #orclive{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.iris-memory #orclive path{fill:none}
.iris-memory #orclive .ray{stroke:rgba(212,236,246,.5);stroke-width:1}.iris-memory #orclive .ray.acted{stroke:var(--brand);stroke-width:1.6}
.iris-memory #orclive .arc{stroke:rgba(212,236,246,.35);stroke-width:3}.iris-memory #orclive .arc.on{stroke:var(--white);stroke-width:4}
.iris-memory #follow:hover{color:var(--dim)} .iris-memory #follow b{font-weight:400;color:var(--amber)}
.iris-memory #follow .dot{display:inline-block;width:5px;height:5px;border-radius:50%;margin-right:.7em;vertical-align:1px;border:1px solid var(--faint)}
.iris-memory #follow .dot.on{background:var(--brand);border-color:var(--brand);box-shadow:0 0 6px var(--brand);animation:iris-mem-live 2.4s ease-in-out infinite}
.iris-memory #crumb .when.pulse{animation:iris-mem-live 1.2s ease-in-out infinite}
.iris-memory #crumb .chat{display:block;width:max-content;margin-top:6px;color:var(--brand);cursor:pointer;pointer-events:auto}.iris-memory #crumb .chat:hover{color:var(--white)}
@keyframes iris-mem-live{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.iris-memory #follow .dot.on,.iris-memory #crumb .when.pulse{animation:none}}
.iris-memory #ticker .dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:.7em;vertical-align:1px}
.iris-memory #lenses{position:absolute;left:50%;bottom:20px;transform:translateX(-50%);display:flex;gap:26px;pointer-events:auto}
.iris-memory #lenses a{font-size:11px;letter-spacing:.22em;color:var(--faint);cursor:pointer;text-transform:lowercase;user-select:none;transition:color .25s}
.iris-memory #lenses a:hover{color:var(--dim)} .iris-memory #lenses a.on{color:var(--white);text-shadow:0 0 12px rgba(0,212,255,.6)}
.iris-memory #key{position:absolute;right:22px;bottom:104px;display:flex;flex-direction:column;gap:9px;pointer-events:auto;opacity:0;transition:opacity .5s}
.iris-memory #key.on{opacity:1}.iris-memory #key:not(.on){pointer-events:none}
.iris-memory #key a{display:flex;align-items:center;justify-content:flex-end;gap:9px;font-size:10px;letter-spacing:.08em;color:var(--faint);cursor:pointer;user-select:none;transition:color .25s,opacity .25s}
.iris-memory #key a:hover{color:var(--dim)}.iris-memory #key a .kn{font-style:normal;color:var(--dim);font-variant-numeric:tabular-nums;min-width:3.4em;text-align:right;opacity:.8}.iris-memory #key a.on{color:var(--white)}.iris-memory #key.iso a:not(.on){opacity:.35}.iris-memory #key canvas{width:22px;height:22px}
.iris-memory #hint{position:absolute;right:22px;bottom:22px;font-size:10px;color:var(--faint);text-align:right;line-height:1.8}
.iris-memory #scrub{position:absolute;left:50%;bottom:56px;width:min(520px,60vw);height:24px;transform:translateX(-50%);
  pointer-events:auto;cursor:ew-resize;opacity:0;transition:opacity .4s}
.iris-memory #scrub.on{opacity:1}
.iris-memory #scrub .track{position:absolute;left:0;right:0;top:12px;height:1px;background:var(--faint)}
.iris-memory #scrub .fill{position:absolute;left:0;top:12px;height:1px;background:var(--brand);box-shadow:0 0 8px var(--brand)}
.iris-memory #scrub .lbl{position:absolute;right:0;top:-4px;font-size:9.5px;color:var(--dim);letter-spacing:.06em}
.iris-memory #scrub .lbl0{position:absolute;left:0;top:-4px;font-size:9.5px;color:var(--faint)}
.iris-memory #search{position:absolute;left:0;right:0;top:0;padding:22px 16px 56px;text-align:center;opacity:0;transition:opacity .3s;pointer-events:none;
  background:linear-gradient(180deg,rgba(2,3,6,.94) 0%,rgba(2,3,6,.86) 62%,rgba(2,3,6,0) 100%)}
.iris-memory.searching #brand,.iris-memory.searching #stats,.iris-memory.searching #crumb{opacity:.12;transition:opacity .3s}
.iris-memory #search.on{opacity:1;pointer-events:auto}
.iris-memory #search input{background:transparent;border:0;border-bottom:1px solid var(--faint);color:var(--white);
  font:300 18px 'Inter Tight',sans-serif;width:min(420px,70vw);text-align:center;outline:none;padding:4px 0}
.iris-memory #search #qres{font-size:10px;color:var(--dim);margin:6px auto 0;letter-spacing:.06em;width:min(560px,86%);max-height:min(46vh,420px);overflow-y:auto;scrollbar-width:none}
.iris-memory #qres .qh{display:block;margin-bottom:8px}.iris-memory #qres .qh b{font-weight:400;color:var(--amber)}.iris-memory #qres.busy .qh{opacity:.45}
.iris-memory #qres .r{display:block;text-align:left;padding:4px 0 4px 6.2em;text-indent:-6.2em;cursor:pointer;color:var(--dim);font-size:11px;line-height:1.35;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .15s}
.iris-memory #qres .r .kw{display:inline-block;width:6.2em;text-indent:0;color:var(--faint);letter-spacing:.14em;font-size:9.5px}
.iris-memory #qres .r .why{display:block;text-indent:0;color:var(--faint);font-size:9.5px;overflow:hidden;text-overflow:ellipsis}
.iris-memory #qres .r.on{color:var(--white)}.iris-memory #qres .r.on .kw{color:var(--brand)}.iris-memory #qres .r.on .why{color:var(--dim)}
.iris-memory #qres .r.gone .tt{opacity:.55;font-style:italic}
.iris-memory #flash{position:absolute;inset:0;background:#fff;opacity:0;pointer-events:none}
.iris-memory /* thread rail: the session's neurons and tasks laid out in time; click one to travel there */
#rail{position:absolute;left:50%;bottom:52px;transform:translateX(-50%);width:min(680px,76vw);height:40px;pointer-events:auto;opacity:0;transition:opacity .4s}
.iris-memory #rail.on{opacity:1}
.iris-memory #rail svg{width:100%;height:28px;overflow:visible;display:block}
.iris-memory #rail .rl{font-size:10px;color:#9fb8c6;text-align:center;height:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 0 4px #000}
.iris-memory #rail circle,.iris-memory #rail rect{cursor:pointer}
.iris-memory #err{position:absolute;inset:0;display:none;align-items:center;justify-content:center;font-size:12px;color:var(--dim)}
.iris-memory #lenses a{white-space:nowrap}
@media (max-width:700px){.iris-memory #lenses{gap:14px;bottom:16px}.iris-memory #lenses a{letter-spacing:.1em}.iris-memory #hint,.iris-memory #stats{display:none}
  .iris-memory #ticker{max-width:calc(100vw - 32px);left:16px;bottom:48px}.iris-memory #follow{left:16px;bottom:92px}.iris-memory #mine{left:16px;bottom:110px;max-width:calc(100vw - 32px)}.iris-memory #scrub{bottom:104px;width:calc(100vw - 32px)}.iris-memory #brand,.iris-memory #local{left:16px}}
`;

export const MEMORY_HTML = String.raw`<canvas id="gl"></canvas>
<div id="vignette"></div>
<canvas id="tissue"></canvas>
<svg id="leaders"></svg>
<div id="labels"></div>
<div id="annos"></div>
<div id="hud">
  <div id="brand">IRIS <span>· MEMORY</span></div>
  <div id="local">everything here lives on this machine</div>
  <div id="crumb"></div>
  <div class="corner tl"></div><div class="corner tr"></div><div class="corner bl"></div><div class="corner br"></div>
  <div id="stats"></div>
  <div id="title"></div>
  <div id="ticker"><div class="line old"></div><div class="line"></div></div>
  <nav id="lenses"></nav>
  <div id="scrub"><span class="lbl0"></span><span class="lbl"></span><div class="track"></div><div class="fill"></div></div>
  <div id="rail"><svg></svg><div class="rl"></div></div>
  <div id="search"><input id="q" placeholder="search what IRIS remembers" autocomplete="off"><div id="qres"></div></div>
  <div id="key"></div>
  <div id="hint"></div>
</div>
<div id="flash"></div>
<div id="err">This view needs WebGL2.</div>`;
