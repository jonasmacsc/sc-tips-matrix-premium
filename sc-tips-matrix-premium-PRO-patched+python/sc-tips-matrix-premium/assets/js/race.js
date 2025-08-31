
export const EU_WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26];

export function drawRaceBoard(canvas){
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth;
  const h = canvas.height = canvas.clientHeight;
  ctx.clearRect(0,0,w,h);
  const cx = w/2, cy = h/2, R = Math.min(w,h)/2 - 20;
  ctx.beginPath(); ctx.arc(cx,cy,R,0,Math.PI*2); ctx.strokeStyle = '#7d6320'; ctx.lineWidth = 2; ctx.stroke();
  ctx.font = '12px ui-monospace, monospace';
  ctx.textAlign='center'; ctx.textBaseline='middle';
  const n = EU_WHEEL.length;
  for(let i=0;i<n;i++){
    const a = -Math.PI/2 + i*(Math.PI*2/n);
    const x = cx + Math.cos(a)*(R-14);
    const y = cy + Math.sin(a)*(R-14);
    const val = EU_WHEEL[i];
    ctx.fillStyle = (val===0)?'#7cff8a':( [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36].includes(val) ? '#ff6a6a' : '#d0d0d0');
    ctx.fillText(String(val), x, y);
  }
}
