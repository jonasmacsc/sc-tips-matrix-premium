
export const HookBus = new EventTarget();

(function(){
  const _WS = window.WebSocket;
  if(!_WS) return;

  window.__SC_WS_URLS__ = [];
  function emit(type, detail){ HookBus.dispatchEvent(new CustomEvent(type,{detail})); }

  window.WebSocket = function(url, protocols){
    try{ window.__SC_WS_URLS__.push(String(url)); emit('ws:url',{url:String(url)}); }catch{}
    const ws = protocols ? new _WS(url, protocols) : new _WS(url);
    const _onmessage = ws.onmessage;
    ws.onmessage = function(ev){
      try{
        const txt = (typeof ev.data==='string')? ev.data : '';
        if(txt.includes('roulette.winSpots') || txt.includes('winningNumber')){
          let num = null, dealer = null;
          try{
            const obj = JSON.parse(txt);
            if(obj?.args?.result?.[0]?.number!=null) num = obj.args.result[0].number;
            if(obj?.args?.dealer) dealer = obj.args.dealer;
            if(obj?.winningNumber!=null) num = obj.winningNumber;
            if(obj?.dealer) dealer = obj.dealer;
          }catch{}
          if(num!=null){ emit('ws:number',{number:Number(num), dealer: dealer||null, raw:txt.slice(0,400)}); }
        }
      }catch{}
      if(typeof _onmessage === 'function') _onmessage.call(this, ev);
    };
    return ws;
  };
  window.WebSocket.prototype = _WS.prototype;
  window.WebSocket.OPEN = _WS.OPEN;
  window.WebSocket.CLOSED = _WS.CLOSED;
  window.WebSocket.CONNECTING = _WS.CONNECTING;
  window.WebSocket.CLOSING = _WS.CLOSING;
})();
