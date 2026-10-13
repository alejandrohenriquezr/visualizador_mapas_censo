/* V41: correcciones de cruces, resumen textual, pirámide, fullscreen y PNG. */
(function instalarCorreccionesV41(){
  'use strict';
  if(window.__visorV41Instalado) return;
  window.__visorV41Instalado = true;

  function resultadoV41(){
    try{
      if(typeof resultadoActual !== 'undefined' && resultadoActual) return resultadoActual;
    }catch(_e){}
    return null;
  }

  function numeroV41(valor, decimales=1){
    const n = Number(valor);
    if(!Number.isFinite(n)) return 'Sin datos';
    return n.toLocaleString('es-CL', {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales
    });
  }

  function enteroV41(valor){
    const n = Number(valor);
    return Number.isFinite(n) ? Math.round(n).toLocaleString('es-CL') : '0';
  }

  function codigoV41(valor){
    const s = String(valor ?? '');
    return /^\d+$/.test(s) ? String(Number(s)) : s;
  }

  function etiquetaResumenV41(etiqueta){
    const t = String(etiqueta ?? '').trim();
    if(/^hombre$/i.test(t)) return 'hombres';
    if(/^mujer$/i.test(t)) return 'mujeres';
    return t;
  }

  function unidadV41(data, cantidad){
    const entidad = String(
      data?.entidad_objetivo || data?.interpretacion?.tabla || ''
    ).toLowerCase();
    if(entidad.includes('hogar')) return cantidad === 1 ? 'hogar' : 'hogares';
    if(entidad.includes('vivienda')) return cantidad === 1 ? 'vivienda' : 'viviendas';
    return cantidad === 1 ? 'persona' : 'personas';
  }

  function nombreAmbitoV41(data){
    let nombre = String(data?.nombre_ambito || data?.resumen_ambito?.nombre || 'Ámbito consultado').trim();
    if(/^chile$/i.test(nombre)) nombre = 'País';
    return nombre;
  }

  function resumenPrimeraDimensionV41(data){
    if(data?.tipo_visualizacion !== 'tortas_mapa' || !Array.isArray(data?.datos)) return null;
    const totales = new Map();
    const etiquetas = new Map();

    for(const territorio of data.datos){
      const dist = Array.isArray(territorio?.distribucion) ? territorio.distribucion : [];
      for(const item of dist){
        const codigo = String(item?.codigo ?? item?.etiqueta ?? '');
        if(!codigo) continue;
        const valor = Number(item?.valor) || 0;
        totales.set(codigo, (totales.get(codigo) || 0) + valor);
        if(!etiquetas.has(codigo)) etiquetas.set(codigo, String(item?.etiqueta ?? codigo));
      }
    }
    if(!totales.size) return null;

    const ordenPreferido = (Array.isArray(data?.categorias_grafico) ? data.categorias_grafico : [])
      .map(x => String(x?.codigo ?? ''))
      .filter(c => totales.has(c));
    const resto = [...totales.keys()].filter(c => !ordenPreferido.includes(c));
    const orden = [...ordenPreferido, ...resto];
    const total = [...totales.values()].reduce((a,b)=>a+b,0);
    return orden.map(codigo => ({
      codigo,
      etiqueta: etiquetas.get(codigo) || codigo,
      valor: totales.get(codigo) || 0,
      porcentaje: total ? 100 * (totales.get(codigo) || 0) / total : null
    }));
  }

  function unirEspanolV41(partes){
    if(partes.length <= 1) return partes[0] || '';
    if(partes.length === 2) return `${partes[0]} y ${partes[1]}`;
    return `${partes.slice(0,-1).join(', ')} y ${partes.at(-1)}`;
  }

  function renderResumenTextualV41(data){
    const panel = document.getElementById('resumen-ambito-v40');
    if(!panel || data?.tipo_visualizacion !== 'tortas_mapa') return;
    if(document.fullscreenElement || document.body.classList.contains('v41-piramide-activa')){
      panel.classList.remove('visible');
      return;
    }
    const dist = resumenPrimeraDimensionV41(data);
    if(!dist?.length){ panel.classList.remove('visible'); return; }

    const partes = dist.map(item => {
      const cantidad = Math.round(Number(item.valor) || 0);
      return `${numeroV41(item.porcentaje,1)}% ${etiquetaResumenV41(item.etiqueta)} (${enteroV41(cantidad)} ${unidadV41(data,cantidad)})`;
    });
    panel.replaceChildren();
    const p = document.createElement('p');
    p.className = 'resumen-texto-v41';
    p.textContent = `${nombreAmbitoV41(data)}: ${unirEspanolV41(partes)}.`;
    panel.appendChild(p);
    panel.classList.add('visible');
  }

  // V40 dibuja inicialmente el resumen; si lo reemplaza después de una consulta,
  // este observador vuelve a aplicar la versión textual solicitada.
  const panelResumen = document.getElementById('resumen-ambito-v40');
  if(panelResumen){
    let rehaciendo = false;
    new MutationObserver(() => {
      if(rehaciendo) return;
      const data = resultadoV41();
      if(data?.tipo_visualizacion !== 'tortas_mapa') return;
      if(panelResumen.querySelector('.resumen-texto-v41')) return;
      rehaciendo = true;
      queueMicrotask(() => {
        try{ renderResumenTextualV41(data); }
        finally{ rehaciendo = false; }
      });
    }).observe(panelResumen,{childList:true,subtree:true});
  }

  function piramideActivaV41(){
    const inline = document.getElementById('piramide-edad');
    const modal = document.getElementById('modal-piramide-v36');
    const inlineVisible = inline && getComputedStyle(inline).display !== 'none';
    const modalVisible = modal && getComputedStyle(modal).display !== 'none';
    return Boolean(inlineVisible || modalVisible);
  }

  async function ajustarMapaResultadoV41(data, padding=34){
    try{
      if(typeof mapa === 'undefined' || !mapa || !data?.geometria || typeof cargarGeometria !== 'function') return;
      const geo = await cargarGeometria(data.geometria);
      const codigos = new Set((data.datos || []).map(x => codigoV41(x?.codigo)));
      const features = (geo?.features || []).filter(f => !codigos.size || codigos.has(codigoV41(f?.properties?.codigo)));
      const coleccion = {type:'FeatureCollection',features:features.length?features:(geo?.features||[])};
      if(!coleccion.features.length) return;
      const temporal = L.geoJSON(coleccion);
      const bounds = temporal.getBounds();
      if(bounds?.isValid()){
        mapa.fitBounds(bounds,{padding:[padding,padding],animate:false,maxZoom:10});
      }
    }catch(_e){}
  }

  function sincronizarPiramideV41(){
    const activa = piramideActivaV41();
    const antes = document.body.classList.contains('v41-piramide-activa');
    document.body.classList.toggle('v41-piramide-activa', activa);
    if(activa){
      document.getElementById('resumen-ambito-v40')?.classList.remove('visible');
      document.getElementById('leyenda')?.classList.remove('visible');
    }else if(antes){
      setTimeout(async()=>{
        try{ if(typeof mapa !== 'undefined') mapa.invalidateSize(false); }catch(_e){}
        await ajustarMapaResultadoV41(resultadoV41());
        renderResumenTextualV41(resultadoV41());
      },30);
    }
  }

  const piramideInline = document.getElementById('piramide-edad');
  if(piramideInline){
    new MutationObserver(sincronizarPiramideV41)
      .observe(piramideInline,{attributes:true,attributeFilter:['class','style','hidden']});
  }
  new MutationObserver(() => sincronizarPiramideV41())
    .observe(document.body,{childList:true,subtree:false});
  document.addEventListener('click', event => {
    const texto = String(event.target?.textContent || '').toLowerCase();
    if(texto.includes('pirámide') || texto.includes('piramide') || texto.includes('mapa')){
      setTimeout(sincronizarPiramideV41,0);
      setTimeout(sincronizarPiramideV41,80);
    }
  },true);
  sincronizarPiramideV41();

  document.addEventListener('fullscreenchange', () => {
    setTimeout(async()=>{
      try{ if(typeof mapa !== 'undefined') mapa.invalidateSize(false); }catch(_e){}
      await ajustarMapaResultadoV41(resultadoV41(), document.fullscreenElement ? 48 : 30);
      if(!document.fullscreenElement) renderResumenTextualV41(resultadoV41());
    },60);
  });

  async function cargarHtml2CanvasV41(){
    if(window.html2canvas) return window.html2canvas;
    return new Promise((resolve,reject)=>{
      const existente = document.querySelector('script[data-html2canvas-v41],script[data-html2canvas-v40]');
      if(existente){
        if(window.html2canvas){ resolve(window.html2canvas); return; }
        existente.addEventListener('load',()=>resolve(window.html2canvas),{once:true});
        existente.addEventListener('error',()=>reject(new Error('No se pudo cargar html2canvas.')),{once:true});
        return;
      }
      const s=document.createElement('script');
      s.dataset.html2canvasV41='1';
      s.src='https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
      s.crossOrigin='anonymous';
      s.onload=()=>window.html2canvas?resolve(window.html2canvas):reject(new Error('html2canvas no quedó disponible.'));
      s.onerror=()=>reject(new Error('No se pudo cargar el componente de exportación PNG.'));
      document.head.appendChild(s);
    });
  }

  async function esperarTilesV41(timeoutMs=2500){
    const inicio=Date.now();
    while(Date.now()-inicio < timeoutMs){
      const tiles=[...document.querySelectorAll('#mapa img.leaflet-tile')]
        .filter(img=>getComputedStyle(img).visibility!=='hidden');
      if(!tiles.length || tiles.every(img=>img.complete && img.naturalWidth>0)) return;
      await new Promise(r=>setTimeout(r,80));
    }
  }

  async function guardarPngV41(){
    const main=document.querySelector('main');
    if(!main) return;
    const boton=document.getElementById('btn-save-png-v40');
    if(boton) boton.disabled=true;
    document.body.classList.add('exportando-v40','exportando-v41');
    try{
      if(document.body.classList.contains('v41-piramide-activa')){
        throw new Error('Vuelve a la pestaña Mapa antes de guardar la imagen.');
      }
      try{ if(typeof mapa !== 'undefined') mapa.invalidateSize(false); }catch(_e){}
      // La exportación siempre debe encuadrar el ámbito consultado, no conservar
      // un zoom residual de una vista anterior o de la transición a fullscreen.
      await ajustarMapaResultadoV41(resultadoV41(), document.fullscreenElement ? 48 : 34);
      await esperarTilesV41();
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const h2c=await cargarHtml2CanvasV41();
      const rect=main.getBoundingClientRect();
      const canvas=await h2c(main,{
        useCORS:true,
        allowTaint:false,
        backgroundColor:'#f6f3ec',
        scale:2,
        logging:false,
        width:Math.max(1,Math.round(rect.width)),
        height:Math.max(1,Math.round(rect.height))
      });
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      if(!blob) throw new Error('No fue posible construir el archivo PNG.');
      const now=new Date();const pad=n=>String(n).padStart(2,'0');
      const nombre=`mapa_censo_${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.png`;
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');a.href=url;a.download=nombre;a.style.display='none';
      document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1200);
    }catch(e){
      const msg='No se pudo exportar el mapa a PNG. '+(e?.message||'');
      try{
        if(typeof mostrarFallo==='function') mostrarFallo(msg); else window.alert(msg);
      }catch(_e){ window.alert(msg); }
    }finally{
      document.body.classList.remove('exportando-v40','exportando-v41');
      if(boton) boton.disabled=false;
    }
  }

  // Sustituye únicamente el listener del botón de guardar; no toca el de fullscreen.
  const guardarAnterior=document.getElementById('btn-save-png-v40');
  if(guardarAnterior && guardarAnterior.dataset.v41!=='1'){
    const clon=guardarAnterior.cloneNode(true);
    clon.dataset.v41='1';
    guardarAnterior.replaceWith(clon);
    clon.addEventListener('click',event=>{
      event.preventDefault();
      event.stopPropagation();
      guardarPngV41();
    });
  }

  // Al terminar de pintar una torta, deja el resumen textual sincronizado.
  const pintarAnterior = window.pintarTortasMapa;
  if(typeof pintarAnterior === 'function' && !pintarAnterior.__v41){
    const envoltura = async function(data){
      const salida = await pintarAnterior(data);
      setTimeout(()=>renderResumenTextualV41(data),25);
      return salida;
    };
    envoltura.__v41=true;
    window.pintarTortasMapa=envoltura;
  }

  const acciones=document.getElementById('acciones-resultado');
  if(acciones){
    new MutationObserver(()=>{
      if(acciones.classList.contains('visible')){
        setTimeout(()=>{
          renderResumenTextualV41(resultadoV41());
          sincronizarPiramideV41();
        },30);
      }
    }).observe(acciones,{attributes:true,attributeFilter:['class']});
  }
})();
