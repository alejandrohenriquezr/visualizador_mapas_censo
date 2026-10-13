/* V41: correcciones de cruces, resumen textual, pirámide y pantalla completa. */
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
