(function () {
'use strict';

/* ═══════════════════════════════════════════════════════════════
   CANVAS & RESIZE
   Canvas stays position:fixed on all viewports.
   On mobile #ui is transparent so the fixed sky shows through.
═════════════════════════════════════════════════════════════════ */
var canvas  = document.getElementById('sky');
if (!canvas) return;
var ctx     = canvas.getContext('2d');
var heroMedia = document.getElementById('hero-media');
var CW, CH, VW, VH, IS_MOBILE;

function resize () {
  var dpr = window.devicePixelRatio || 1;
  IS_MOBILE = window.innerWidth <= 680;
  VW = window.innerWidth;
  VH = window.innerHeight;
  CW = canvas.width  = VW * dpr;
  CH = canvas.height = VH * dpr;
  canvas.style.width  = VW + 'px';
  canvas.style.height = VH + 'px';
}

/* Defer first resize to rAF so iOS Safari completes layout first */
requestAnimationFrame(function () {
  resize();
  requestAnimationFrame(tick);
});
window.addEventListener('resize', resize);

/* ═══════════════════════════════════════════════════════════════
   BACKGROUND STARS
═════════════════════════════════════════════════════════════════ */
var field = [];
for (var i = 0; i < 420; i++) {
  var isBright  = Math.random() < 0.08;
  var speedTier = Math.random();
  var ts = speedTier < 0.2  ? 0.002 + Math.random() * 0.003
         : speedTier < 0.85 ? 0.006 + Math.random() * 0.01
                             : 0.02  + Math.random() * 0.025;
  var ta = speedTier < 0.2  ? 0.04  + Math.random() * 0.08
         : speedTier < 0.85 ? 0.08  + Math.random() * 0.18
                             : 0.25  + Math.random() * 0.35;
  field.push({
    x: Math.random(), y: Math.pow(Math.random(), 1.4) * 0.93,
    r: isBright ? 0.8 + Math.random() * 0.9 : 0.2 + Math.random() * 0.55,
    a: 0.08 + Math.random() * 0.55,
    tw: Math.random() * Math.PI * 2, ts: ts, ta: ta,
    warm: Math.random() < 0.08, shimmerLife: 0
  });
}
var nextShimmer = 8000 + Math.random() * 22000;
var shimmerIdx  = null;

var milky = [];
for (var m = 0; m < 18; m++) {
  milky.push({
    xf: 0.05 + (m / 17) * 0.9,
    yf: 0.15 + Math.sin(m * 0.55) * 0.12 + (m / 17) * 0.35,
    rx: 0.06 + Math.random() * 0.05,
    ry: 0.04 + Math.random() * 0.03,
    a:  0.012 + Math.random() * 0.018
  });
}

var orion = [
  { xf: 0.56, yf: 0.36, r: 0.9, a: 0.28 },
  { xf: 0.40, yf: 0.38, r: 0.7, a: 0.18 },
  { xf: 0.60, yf: 0.27, r: 0.7, a: 0.22 },
  { xf: 0.47, yf: 0.41, r: 0.6, a: 0.16 },
  { xf: 0.38, yf: 0.29, r: 0.65,a: 0.18 },
  { xf: 0.55, yf: 0.20, r: 0.6, a: 0.13 }
];

var shoot     = null;
var nextShoot = 5000 + Math.random() * 12000;

/* ═══════════════════════════════════════════════════════════════
   3-D PHYSICS CONSTELLATION — ROHINI / SHAKATA
   5 stars of the Hyades cluster corresponding to Rohini nakshatra.
   α Tau (Aldebaran) is the Yogatara — the red junction star at
   the tip of the V-arrowhead. Four lines radiate from it.
   γ, δ (left arm), ε, θ² (right arm) form the V above.

   Shape (V opens upward, Aldebaran at bottom tip):

        γ           ε
        │╲         ╱│
        │  δ──── θ² │
        │   ╲  ╱   │
        └────α──────┘
             (Aldebaran — red, warm, all arms converge)

   Connections: α→γ, α→δ, α→ε, α→θ²  (4 ribs from Aldebaran)
                γ→δ, ε→θ²              (2 cross-bars on each arm)
═══════════════════════════════════════════════════════════════ */
var S = [
  /* 0 — α Tauri — Aldebaran — bottom tip, warm orange-red, junction star */
  { label: 'α',  sub: 'रोहिणी', rest: [   0,  95,  25], pos: [   0,  95,  25], vel: [0,0,0], mass: 2.8, r: 3.0, col: '222,152,84'  },
  /* 1 — γ Tauri — Prima Hyadum — upper-left outer */
  { label: 'γ',  sub: null,      rest: [-108, -88,   8], pos: [-108, -88,   8], vel: [0,0,0], mass: 1.5, r: 1.7, col: '228,218,200' },
  /* 2 — δ¹ Tauri — Secunda Hyadum — upper-left inner */
  { label: 'δ',  sub: null,      rest: [ -50, -30,  12], pos: [ -50, -30,  12], vel: [0,0,0], mass: 1.4, r: 1.5, col: '226,216,198' },
  /* 3 — ε Tauri — Ain — upper-right outer */
  { label: 'ε',  sub: null,      rest: [ 105, -82,  -8], pos: [ 105, -82,  -8], vel: [0,0,0], mass: 1.5, r: 1.6, col: '224,214,195' },
  /* 4 — θ² Tauri — upper-right inner */
  { label: 'θ²', sub: null,      rest: [  52, -22, -12], pos: [  52, -22, -12], vel: [0,0,0], mass: 1.3, r: 1.4, col: '222,212,193' },
];

/*
  V-arrowhead connections — Aldebaran as hub:
    α → γ   left outer arm (long)
    α → δ   left inner arm (short)
    α → ε   right outer arm (long)
    α → θ²  right inner arm (short)
    γ → δ   left arm cross-bar
    ε → θ²  right arm cross-bar
*/
var SHAKATA = [[0,1],[0,2],[0,3],[0,4],[1,2],[3,4]];

var SP = [];
for (var si = 0; si < S.length; si++) {
  for (var sj = si + 1; sj < S.length; sj++) {
    var ra = S[si].rest, rb = S[sj].rest;
    var draw = SHAKATA.some(function (p) {
      return (p[0]===si && p[1]===sj) || (p[0]===sj && p[1]===si);
    });
    SP.push({
      a: si, b: sj,
      len0: Math.hypot(rb[0]-ra[0], rb[1]-ra[1], rb[2]-ra[2]),
      tension: 0,
      draw: draw
    });
  }
}

var K_HOME   = 0.055;   /* moderate home spring */
var K_LINK   = 0.022;
var DAMP     = 0.920;
var BREATH_A = 16.0;    /* visible but not excessive */
var BREATH_W = 0.13;
var NOISE    = 0.18;    /* gentle Brownian drift */
var AUTO_SPIN = 0.000055;

var rotX = -0.24, rotY = 0.32;
var vRotX = 0,    vRotY = AUTO_SPIN;
var PTR = { down: false, px: 0, py: 0, star: -1 };

function rotMat (rx, ry) {
  var cx = Math.cos(rx), sx = Math.sin(rx);
  var cy = Math.cos(ry), sy = Math.sin(ry);
  return [ cy, sy*sx, sy*cx, 0, cx, -sx, -sy, cy*sx, cy*cx ];
}
function mv3 (M, v) {
  return [ M[0]*v[0]+M[1]*v[1]+M[2]*v[2], M[3]*v[0]+M[4]*v[1]+M[5]*v[2], M[6]*v[0]+M[7]*v[1]+M[8]*v[2] ];
}
function mvT3 (M, v) {
  return [ M[0]*v[0]+M[3]*v[1]+M[6]*v[2], M[1]*v[0]+M[4]*v[1]+M[7]*v[2], M[2]*v[0]+M[5]*v[1]+M[8]*v[2] ];
}

var FL = 680;

function project (local, M) {
  var dpr = window.devicePixelRatio || 1;
  var sc  = Math.min(VW, VH) * (IS_MOBILE ? 0.0032 : 0.0024);
  var w   = mv3(M, local);
  var p   = FL / (FL + w[2] * sc);

  var originX, originY;
  if (IS_MOBILE) {
    var scrollFrac = Math.min(Math.max((window.scrollY || window.pageYOffset) / VH, 0), 1);
    originX = VW * 0.50;
    originY = VH * (1.35 - scrollFrac * 0.87);
  } else {
    var heroRect = heroMedia ? heroMedia.getBoundingClientRect() : { width: VW, height: VH };
    originX = heroRect.width * 0.70;
    originY = heroRect.height * 0.42;
  }

  return {
    x:  (originX + w[0] * sc * p) * dpr,
    y:  (originY + w[1] * sc * p) * dpr,
    cx:  originX + w[0] * sc * p,
    cy:  originY + w[1] * sc * p,
    p:  p, sc: sc
  };
}

function physStep (t) {
  for (var i = 0; i < S.length; i++) {
    var s = S[i];
    if (s._grabbed) continue;
    var fx = (s.rest[0] - s.pos[0]) * K_HOME;
    var fy = (s.rest[1] - s.pos[1]) * K_HOME;
    var fz = (s.rest[2] - s.pos[2]) * K_HOME;
    var ph = t * BREATH_W + i * 2.094;
    fx += Math.sin(ph * 1.31) * BREATH_A * 0.015;
    fy += Math.cos(ph * 0.79) * BREATH_A * 0.015;
    fz += Math.sin(ph * 1.07) * BREATH_A * 0.007;
    fx += (Math.random() - 0.5) * NOISE;
    fy += (Math.random() - 0.5) * NOISE;
    fz += (Math.random() - 0.5) * NOISE * 0.35;
    s.vel[0] = (s.vel[0] + fx / s.mass) * DAMP;
    s.vel[1] = (s.vel[1] + fy / s.mass) * DAMP;
    s.vel[2] = (s.vel[2] + fz / s.mass) * DAMP;
    s.pos[0] += s.vel[0];
    s.pos[1] += s.vel[1];
    s.pos[2] += s.vel[2];
  }
  for (var k = 0; k < SP.length; k++) {
    var sp = SP[k];
    var sa = S[sp.a], sb = S[sp.b];
    var dx = sb.pos[0]-sa.pos[0], dy = sb.pos[1]-sa.pos[1], dz = sb.pos[2]-sa.pos[2];
    var dist = Math.hypot(dx, dy, dz) || 1e-9;
    var stretch = (dist - sp.len0) / sp.len0;
    sp.tension = stretch;
    var f = stretch * K_LINK;
    var nx = dx/dist, ny = dy/dist, nz = dz/dist;
    if (!sa._grabbed) { sa.vel[0] += nx*f/sa.mass; sa.vel[1] += ny*f/sa.mass; sa.vel[2] += nz*f/sa.mass; }
    if (!sb._grabbed) { sb.vel[0] -= nx*f/sb.mass; sb.vel[1] -= ny*f/sb.mass; sb.vel[2] -= nz*f/sb.mass; }
  }
}

function drawConstellation (M) {
  var dpr = window.devicePixelRatio || 1;
  var proj = S.map(function (s) {
    var p = project(s.pos, M);
    p.speed = Math.hypot(s.vel[0], s.vel[1], s.vel[2]);
    return p;
  });

  for (var k = 0; k < SP.length; k++) {
    var sp = SP[k];
    if (!sp.draw) continue;
    var pa = proj[sp.a], pb = proj[sp.b];
    var ten = Math.abs(sp.tension);
    ctx.save();
    ctx.strokeStyle = 'rgba(184,154,90,' + Math.min(0.06+ten*1.2,0.3).toFixed(3) + ')';
    ctx.lineWidth = (5.0+ten*18)*dpr;
    ctx.beginPath(); ctx.moveTo(pa.x,pa.y); ctx.lineTo(pb.x,pb.y); ctx.stroke();
    ctx.strokeStyle = 'rgba(210,175,120,' + Math.min(0.07+ten*2.0,0.55).toFixed(3) + ')';
    ctx.lineWidth = (2.2+ten*9)*dpr;
    ctx.beginPath(); ctx.moveTo(pa.x,pa.y); ctx.lineTo(pb.x,pb.y); ctx.stroke();
    ctx.strokeStyle = 'rgba(235,215,185,' + Math.min(0.20+ten*3.5,0.80).toFixed(3) + ')';
    ctx.lineWidth = 0.8*dpr;
    ctx.beginPath(); ctx.moveTo(pa.x,pa.y); ctx.lineTo(pb.x,pb.y); ctx.stroke();
    ctx.restore();
  }

  S.forEach(function (star, i) {
    var p   = proj[i];
    var spd = p.speed;
    var brt = Math.min(1, 0.72 + spd * 5.0);
    if (i===0) proj[0].brt = brt;
    var r   = star.r * dpr * Math.max(p.p, 0.4);
    var isL = (i === 0);
    var outerCol = isL ? '210,95,35' : '180,160,130';
    var g0 = ctx.createRadialGradient(p.x,p.y,0, p.x,p.y, r*(isL?14:9));
    g0.addColorStop(0, 'rgba('+outerCol+','+(( isL?0.14:0.10)*brt).toFixed(3)+')');
    g0.addColorStop(1, 'rgba('+outerCol+',0)');
    ctx.beginPath(); ctx.arc(p.x,p.y, r*(isL?14:9), 0, Math.PI*2);
    ctx.fillStyle = g0; ctx.fill();
    var g1 = ctx.createRadialGradient(p.x,p.y,0, p.x,p.y, r*4);
    g1.addColorStop(0,    'rgba('+(isL?'255,220,160':'235,228,215')+','+(0.65*brt).toFixed(3)+')');
    g1.addColorStop(0.45, 'rgba('+star.col+','+(0.22*brt).toFixed(3)+')');
    g1.addColorStop(1,    'rgba('+star.col+',0)');
    ctx.beginPath(); ctx.arc(p.x,p.y, r*4, 0, Math.PI*2);
    ctx.fillStyle = g1; ctx.fill();
    var g2 = ctx.createRadialGradient(p.x-r*0.28,p.y-r*0.28,0, p.x,p.y, r);
    g2.addColorStop(0,   'rgba(252,249,247,'+brt.toFixed(3)+')');
    g2.addColorStop(0.5, 'rgba('+star.col+',0.90)');
    g2.addColorStop(1,   'rgba('+star.col+',0.60)');
    ctx.beginPath(); ctx.arc(p.x,p.y, r, 0, Math.PI*2);
    ctx.fillStyle = g2; ctx.fill();
    if (isL) {
      var sl = r*6.5, soa = (0.11+0.06*brt)*brt;
      ctx.save();
      ctx.strokeStyle = 'rgba(230,185,120,'+soa.toFixed(3)+')';
      ctx.lineWidth = 0.7*dpr;
      ctx.beginPath(); ctx.moveTo(p.x-sl,p.y); ctx.lineTo(p.x+sl,p.y); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p.x,p.y-sl); ctx.lineTo(p.x,p.y+sl); ctx.stroke();
      ctx.restore();
    }
    var fsize = Math.round(13*dpr);
    ctx.font = '300 '+fsize+"px 'DM Mono', monospace";
    ctx.fillStyle = isL ? 'rgba(220,180,120,0.78)' : 'rgba(210,200,180,0.60)';
    if (isL) {
      ctx.fillText(star.label, p.x+26*dpr, p.y+fsize*0.4);
      var hfsize = Math.round(11*dpr);
      ctx.font = '300 '+hfsize+"px 'Noto Sans Devanagari', sans-serif";
      ctx.fillStyle = 'rgba(210,140,70,0.60)';
      ctx.textAlign = 'center';
      ctx.fillText('रोहिणी', p.x, p.y + r*3.2 + hfsize + 4*dpr);
      ctx.textAlign = 'left';
    } else {
      var offsets = [
        null,
        [-32*dpr, -8*dpr],
        [-30*dpr,  4*dpr],
        [ 14*dpr, -8*dpr],
        [ 14*dpr,  4*dpr],
      ];
      var off = offsets[i] || [14*dpr, -8*dpr];
      ctx.fillText(star.label, p.x+off[0], p.y+off[1]);
    }
  });
  ctx.textAlign = 'left';
  return {
    alpha: { cx: proj[0].cx, cy: proj[0].cy },
    eps:   { cx: proj[1].cx, cy: proj[1].cy },
    theta: { cx: proj[2].cx, cy: proj[2].cy }
  };
}

function nearStar (mx, my) {
  var M = rotMat(rotX, rotY);
  for (var i = 0; i < S.length; i++) {
    var p = project(S[i].pos, M);
    if (Math.hypot(mx-p.cx, my-p.cy) < 34) return i;
  }
  return -1;
}
function onDown (mx, my) {
  PTR.down = true; PTR.px = mx; PTR.py = my;
  PTR.star = nearStar(mx, my);
  if (PTR.star >= 0) { S[PTR.star]._grabbed = true; document.body.style.cursor = 'grabbing'; }
  vRotX = 0; vRotY = 0;
}
function onMove (mx, my) {
  if (!PTR.down) {
    document.body.style.cursor = nearStar(mx, my) >= 0 ? 'grab' : 'default';
    return;
  }
  var dx = mx-PTR.px, dy = my-PTR.py;
  PTR.px = mx; PTR.py = my;
  if (PTR.star >= 0) {
    var st = S[PTR.star];
    var M  = rotMat(rotX, rotY);
    var w  = mv3(M, st.pos);
    var sc = Math.min(VW,VH) * (IS_MOBILE ? 0.0032 : 0.0024);
    var persp = FL/(FL+w[2]*sc);
    var ld = mvT3(M, [dx/(persp*sc), dy/(persp*sc), 0]);
    st.pos[0]+=ld[0]; st.pos[1]+=ld[1]; st.pos[2]+=ld[2]*0.07;
    st.vel[0]=ld[0]*0.5; st.vel[1]=ld[1]*0.5; st.vel[2]=ld[2]*0.04;
  } else {
    vRotX = dy*0.0065; vRotY = dx*0.0065;
    rotX += vRotX; rotY += vRotY;
  }
}
function onUp () {
  if (PTR.star>=0) { S[PTR.star]._grabbed=false; PTR.star=-1; }
  PTR.down=false; document.body.style.cursor='default';
}

window.addEventListener('mousedown', function(e){
  var idx = nearStar(e.clientX, e.clientY);
  if (idx >= 0) e.preventDefault();
  onDown(e.clientX, e.clientY);
});
window.addEventListener('mousemove', function(e){ onMove(e.clientX,e.clientY); });
window.addEventListener('mouseup',   onUp);

canvas.addEventListener('touchstart', function(e){
  var t = e.touches[0];
  var idx = nearStar(t.clientX, t.clientY);
  if (idx >= 0) e.preventDefault();
  onDown(t.clientX, t.clientY);
}, { passive: false });
canvas.addEventListener('touchmove', function(e){
  if (PTR.star >= 0) e.preventDefault();
  var t = e.touches[0]; onMove(t.clientX, t.clientY);
}, { passive: false });
canvas.addEventListener('touchend', function(e){
  if (PTR.star >= 0) e.preventDefault();
  onUp();
}, { passive: false });

var frameT=0, lastFrameTs=0;
function tick (now) {
  var dt = now - lastFrameTs; lastFrameTs = now;
  frameT += dt * 0.001;
  var dpr = window.devicePixelRatio || 1;

  if (!PTR.down || PTR.star >= 0) {
    rotX += vRotX; rotY += vRotY;
    vRotY += (AUTO_SPIN - vRotY) * 0.005;
    vRotX *= 0.972;
  }
  var M = rotMat(rotX, rotY);
  physStep(frameT);

  ctx.clearRect(0, 0, CW, CH);

  var bg = ctx.createLinearGradient(0,0,0,CH);
  bg.addColorStop(0.00,'rgba(2,4,10,1)');
  bg.addColorStop(0.55,'rgba(4,6,14,1)');
  bg.addColorStop(0.80,'rgba(6,9,22,1)');
  bg.addColorStop(0.92,'rgba(10,14,35,1)');
  bg.addColorStop(1.00,'rgba(14,18,42,1)');
  ctx.fillStyle=bg; ctx.fillRect(0,0,CW,CH);

  for (var mi=0; mi<milky.length; mi++) {
    var b=milky[mi];
    var bx=b.xf*CW,by=b.yf*CH,brx=b.rx*CW,bry=b.ry*CH;
    var g=ctx.createRadialGradient(bx,by,0,bx,by,Math.max(brx,bry));
    g.addColorStop(0,'rgba(180,185,210,'+b.a+')');
    g.addColorStop(1,'rgba(180,185,210,0)');
    ctx.save(); ctx.scale(1,bry/brx);
    ctx.beginPath(); ctx.arc(bx,by*brx/bry,brx,0,Math.PI*2);
    ctx.fillStyle=g; ctx.fill(); ctx.restore();
  }

  nextShimmer -= dt;
  if (nextShimmer<0 && shimmerIdx===null) {
    var cands=[];
    for (var ci=0; ci<field.length; ci++) {
      if (field[ci].r>0.4 && field[ci].r<0.8) cands.push(ci);
    }
    if (cands.length>0) { shimmerIdx=cands[Math.floor(Math.random()*cands.length)]; field[shimmerIdx].shimmerLife=1.0; }
    nextShimmer=12000+Math.random()*25000;
  }
  if (shimmerIdx!==null) {
    field[shimmerIdx].shimmerLife -= dt*0.0006;
    if (field[shimmerIdx].shimmerLife<=0) { field[shimmerIdx].shimmerLife=0; shimmerIdx=null; }
  }

  for (var fi=0; fi<field.length; fi++) {
    var s=field[fi];
    s.tw += s.ts;
    var sa=s.a*(1-s.ta+s.ta*Math.sin(s.tw));
    if (fi===shimmerIdx && s.shimmerLife>0) sa=Math.min(1.0,sa+s.shimmerLife*0.7);
    var sx=s.x*CW, sy=s.y*CH, sr=s.r*dpr;
    var hue=s.warm?'rgba(255,230,200,':'rgba(230,230,240,';
    if (s.r>0.7||(fi===shimmerIdx&&s.shimmerLife>0)) {
      var gm=(fi===shimmerIdx&&s.shimmerLife>0)?5.5:3.5;
      var gg=ctx.createRadialGradient(sx,sy,0,sx,sy,sr*gm);
      gg.addColorStop(0,hue+(sa*0.55)+')'); gg.addColorStop(1,hue+'0)');
      ctx.beginPath(); ctx.arc(sx,sy,sr*gm,0,Math.PI*2); ctx.fillStyle=gg; ctx.fill();
    }
    ctx.beginPath(); ctx.arc(sx,sy,sr,0,Math.PI*2); ctx.fillStyle=hue+sa+')'; ctx.fill();
  }

  for (var oi=0; oi<orion.length; oi++) {
    var o=orion[oi];
    ctx.beginPath(); ctx.arc(o.xf*CW,o.yf*CH,o.r*dpr,0,Math.PI*2);
    ctx.fillStyle='rgba(210,215,240,'+o.a+')'; ctx.fill();
  }

  drawConstellation(M);

  nextShoot -= dt;
  if (nextShoot<0 && !shoot) {
    shoot={
      x:  (0.10 + Math.random() * 0.55) * CW,
      y:  (0.04 + Math.random() * 0.25) * CH,
      vx: (1.8  + Math.random() * 2.8)  * CW  * 0.001,
      vy: (0.4  + Math.random() * 1.2)  * CH  * 0.001,
      life: 1.0,
      len: 70 + Math.random() * 90
    };
    nextShoot = 4000 + Math.random() * 10000;
  }
  if (shoot) {
    shoot.x+=shoot.vx; shoot.y+=shoot.vy; shoot.life-=0.022;
    if (shoot.life<=0) { shoot=null; }
    else {
      var tr=ctx.createLinearGradient(
        shoot.x-shoot.vx*shoot.len, shoot.y-shoot.vy*shoot.len,
        shoot.x, shoot.y
      );
      tr.addColorStop(0,'rgba(220,228,255,0)');
      tr.addColorStop(1,'rgba(220,228,255,'+(shoot.life*0.80)+')');
      ctx.beginPath();
      ctx.moveTo(shoot.x-shoot.vx*shoot.len, shoot.y-shoot.vy*shoot.len);
      ctx.lineTo(shoot.x, shoot.y);
      ctx.strokeStyle=tr; ctx.lineWidth=1.4*dpr; ctx.stroke();
    }
  }

  requestAnimationFrame(tick);
}
})();
