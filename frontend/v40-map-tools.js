/* V40: controles de pantalla completa, PNG, resumen de ámbito y desagregaciones. */
(function instalarMapaV40(){
  'use strict';

  const COLORES_V40=['#2f5d50','#b5652c','#5578a0','#8b6c8e','#9b927c'];
  let capaEtiquetasV40=null;
  let ultimoResultadoV40=null;

  function resultadoV40(){
    try{
      if(typeof resultadoActual!=='undefined' && resultadoActual) return resultadoActual;
    }catch(_e){}
    return ultimoResultadoV40;
  }

  function numeroV40(valor,decimales=1){
    const n=Number(valor);
    return Number.isFinite(n)?n.toLocaleString('es-CL',{maximumFractionDigits:decimales}):'Sin datos';
  }

  function codigoV40(valor){
    const s=String(valor??'');
    return /^\d+$/.test(s)?String(Number(s)):s;
  }

  function puntoInteriorV40(feature){
    const p=feature?.properties||{};
    const lat=Number(p.centro_lat),lon=Number(p.centro_lon);
    if(Number.isFinite(lat)&&Number.isFinite(lon)) return [lat,lon];
    const temporal=L.geoJSON(feature);
    const c=temporal.getBounds().getCenter();
    return [c.lat,c.lng];
  }

  function gradienteV40(distribucion){
    let a=0;
    const tramos=(distribucion||[]).map((item,i)=>{
      const ini=a;a+=Number(item.porcentaje)||0;
      return `${COLORES_V40[i%COLORES_V40.length]} ${ini}% ${a}%`;
    });
    return `conic-gradient(${tramos.join(',')})`;
  }

  function resumenFallbackV40(data){
    const nombre=data?.nombre_ambito||data?.resumen_ambito?.nombre||'Ámbito consultado';
    if(data?.tipo_visualizacion==='tortas_mapa'){
      const totales=new Map(),etiquetas=new Map();
      (data.datos||[]).forEach(t=>{
        const items=t.distribucion_completa||t.distribucion||[];
        items.forEach(x=>{
          const c=String(x.codigo);totales.set(c,(totales.get(c)||0)+(Number(x.valor)||0));
          etiquetas.set(c,x.etiqueta||c);
        });
      });
      if(!totales.size) return null;
      const orden=[...totales.keys()].sort((a,b)=>(totales.get(b)-totales.get(a))||String(etiquetas.get(a)).localeCompare(String(etiquetas.get(b))));
      const principales=orden.slice(0,4), total=[...totales.values()].reduce((a,b)=>a+b,0);
      const dist=principales.map(c=>({codigo:c,etiqueta:etiquetas.get(c),valor:totales.get(c),porcentaje:total?100*totales.get(c)/total:null}));
      if(orden.length>4){const otros=orden.slice(4).reduce((s,c)=>s+totales.get(c),0);dist.push({codigo:'otros',etiqueta:'Otros',valor:otros,porcentaje:total?100*otros/total:null});}
      return {tipo:'torta',nombre,total,distribucion:dist};
    }
    if(data?.tipo_visualizacion==='mapa' && ['conteo'].includes(data?.interpretacion?.operacion)){
      const valores=(data.datos||[]).map(x=>Number(x.valor)).filter(Number.isFinite);
      if(valores.length) return {tipo:'valor',nombre,valor:valores.reduce((a,b)=>a+b,0)};
    }
    return null;
  }

  function renderResumenV40(data){
    const panel=document.getElementById('resumen-ambito-v40');
    if(!panel) return;
    panel.replaceChildren();
    const resumen=data?.resumen_ambito||resumenFallbackV40(data);
    if(!resumen || document.fullscreenElement){panel.classList.remove('visible');return;}
    const h=document.createElement('h3');h.textContent=resumen.nombre||data?.nombre_ambito||'Ámbito consultado';panel.appendChild(h);
    if(resumen.tipo==='valor'){
      const v=document.createElement('div');v.className='resumen-valor-v40';
      const op=data?.interpretacion?.operacion;
      const sufijo=['porcentaje','porcentaje_rango','razon'].includes(op)?' %':'';
      v.textContent=numeroV40(resumen.valor,1)+sufijo;panel.appendChild(v);
    }else if(resumen.tipo==='torta'){
      const wrap=document.createElement('div');wrap.className='resumen-pie-wrap-v40';
      const pie=document.createElement('div');pie.className='resumen-pie-v40';pie.style.background=gradienteV40(resumen.distribucion||[]);
      const lista=document.createElement('div');lista.className='resumen-lista-v40';
      (resumen.distribucion||[]).forEach((x,i)=>{
        const fila=document.createElement('div');fila.className='resumen-fila-v40';
        const color=document.createElement('span');color.className='resumen-color-v40';color.style.background=COLORES_V40[i%COLORES_V40.length];
        const et=document.createElement('span');et.textContent=x.etiqueta||x.codigo;
        const n=document.createElement('span');n.className='resumen-num-v40';n.textContent=`${numeroV40(x.porcentaje,1)} % · ${numeroV40(x.valor,0)}`;
        fila.append(color,et,n);lista.appendChild(fila);
      });
      wrap.append(pie,lista);panel.appendChild(wrap);
    }else if(resumen.tipo==='series'){
      const lista=document.createElement('div');lista.className='resumen-lista-v40';
      (resumen.series||[]).forEach(x=>{
        const fila=document.createElement('div');fila.className='resumen-fila-v40';
        const punto=document.createElement('span');punto.className='resumen-color-v40';punto.style.background=COLORES_V40[0];
        const et=document.createElement('span');et.textContent=x.etiqueta||x.codigo;
        const n=document.createElement('span');n.className='resumen-num-v40';n.textContent=numeroV40(x.valor,2);
        fila.append(punto,et,n);lista.appendChild(fila);
      });
      panel.appendChild(lista);
    }else{panel.classList.remove('visible');return;}
    panel.classList.add('visible');
  }

  function htmlSerieV40(territorio,max=4){
    const series=territorio?.series||territorio?.barras||[];
    const filas=series.slice(0,max).map(x=>`<div class="serie-mini-row-v40"><span>${escapeV40(x.etiqueta||x.variable||'')}</span><span>${numeroV40(x.valor??x.porcentaje,2)}</span></div>`).join('');
    const mas=series.length>max?`<div class="serie-mini-row-v40"><span>Otras categorías</span><span>…</span></div>`:'';
    return `<div class="serie-mini-card-v40"><strong>${escapeV40(territorio?.nombre||'')}</strong>${filas}${mas}</div>`;
  }

  function escapeV40(t){
    return String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  window.pintarSeriesMapaV40=async function pintarSeriesMapaV40(data){
    const territorios=Array.isArray(data?.datos)?data.datos:[];
    if(!territorios.length) throw new Error('No hay resultados desagregados para mostrar.');
    const geo=await cargarGeometria(data.geometria);
    const porCodigo=new Map(territorios.map(t=>[codigoV40(t.codigo),t]));
    const grupo=L.layerGroup();
    const pol=L.geoJSON(geo,{
      style:{fillColor:'#f1eee5',weight:.8,color:'#5d584f',fillOpacity:.35},
      onEachFeature:(feature,layer)=>{
        const t=porCodigo.get(codigoV40(feature.properties?.codigo));
        if(!t) return;
        const div=document.createElement('div');
        const h=document.createElement('strong');h.textContent=t.nombre||'';div.appendChild(h);
        (t.series||[]).forEach(x=>{const f=document.createElement('div');f.textContent=`${x.etiqueta}: ${numeroV40(x.valor,2)}`;div.appendChild(f);});
        layer.bindPopup(div);
      }
    });
    pol.addTo(grupo);
    for(const feature of geo.features||[]){
      const t=porCodigo.get(codigoV40(feature.properties?.codigo));if(!t) continue;
      const icon=L.divIcon({className:'serie-mini-v40',html:htmlSerieV40(t,4),iconSize:null});
      L.marker(puntoInteriorV40(feature),{icon,keyboard:true}).addTo(grupo);
    }
    grupo.addTo(mapa);
    if(typeof capaActual!=='undefined'&&capaActual&&capaActual!==grupo){try{mapa.removeLayer(capaActual);}catch(_e){}}
    if(typeof capaActual!=='undefined') capaActual=grupo;
    document.getElementById('grafico-torta')?.classList.remove('visible');
    document.getElementById('grafico-barras')?.classList.remove('visible');
    document.getElementById('mapa')?.classList.remove('oculto');
    document.getElementById('leyenda')?.classList.remove('visible');
    mapa.invalidateSize(false);
    const b=pol.getBounds();if(b.isValid()) mapa.fitBounds(b,{padding:[24,24],animate:false});
  };

  function iconoMetricaV40(valor,sufijo=''){
    return L.divIcon({className:'etiqueta-metrica-v40',html:`<div>${escapeV40(numeroV40(valor,2)+sufijo)}</div>`,iconSize:null});
  }

  function iconoSerieCentroV40(t){
    const items=t?.series||t?.barras||[];
    const lineas=items.slice(0,6).map(x=>`<div class="serie-linea-v40"><span>${escapeV40(x.etiqueta||x.variable||'')}</span><span>${escapeV40(numeroV40(x.valor??x.porcentaje,2))}</span></div>`).join('');
    return L.divIcon({className:'serie-centro-v40',html:`<div class="serie-card-v40"><strong>${escapeV40(t?.nombre||'')}</strong>${lineas}</div>`,iconSize:null});
  }

  function iconoTortaFullV40(t){
    const dist=t?.distribucion||[];
    let acumulado=0;
    const labels=dist.map((x,i)=>{
      const p=Number(x.porcentaje)||0;const ang=(acumulado+p/2)*3.6;acumulado+=p;
      const texto=`${numeroV40(p,1)} % · ${numeroV40(x.valor,0)}`;
      return `<span class="pie-full-label-v40" style="transform:rotate(${ang}deg) translate(70px) rotate(${-ang}deg)">${escapeV40(texto)}</span>`;
    }).join('');
    return L.divIcon({className:'pie-full-v40',html:`<div class="pie-full-wrap-v40"><div class="pie-full-core-v40" style="background:${gradienteV40(dist)}"></div>${labels}</div>`,iconSize:null});
  }

  async function actualizarEtiquetasFullscreenV40(){
    if(capaEtiquetasV40){try{mapa.removeLayer(capaEtiquetasV40);}catch(_e){}capaEtiquetasV40=null;}
    const data=resultadoV40();
    if(!document.fullscreenElement||!data?.geometria||!['mapa','tortas_mapa','series_mapa','barras_mapa'].includes(data.tipo_visualizacion||'mapa')) return;
    let geo;try{geo=await cargarGeometria(data.geometria);}catch(_e){return;}
    const porCodigo=new Map((data.datos||[]).map(t=>[codigoV40(t.codigo),t]));
    const grupo=L.layerGroup();
    const esPct=['porcentaje','porcentaje_rango','razon'].includes(data?.interpretacion?.operacion);
    for(const feature of geo.features||[]){
      const t=porCodigo.get(codigoV40(feature.properties?.codigo));if(!t) continue;
      let icon;
      if(data.tipo_visualizacion==='tortas_mapa') icon=iconoTortaFullV40(t);
      else if(data.tipo_visualizacion==='series_mapa'||data.tipo_visualizacion==='barras_mapa') icon=iconoSerieCentroV40(t);
      else icon=iconoMetricaV40(t.valor,esPct?' %':'');
      L.marker(puntoInteriorV40(feature),{icon,interactive:false,keyboard:false}).addTo(grupo);
    }
    grupo.addTo(mapa);capaEtiquetasV40=grupo;
  }

  function actualizarIconoPantallaV40(){
    const boton=document.getElementById('btn-fullscreen-v40');if(!boton) return;
    const full=Boolean(document.fullscreenElement);
    boton.title=full?'Contraer mapa':'Mostrar mapa a pantalla completa';
    boton.setAttribute('aria-label',boton.title);
    boton.innerHTML=full
      ?'<svg viewBox="0 0 24 24"><path d="M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6"/></svg>'
      :'<svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg>';
  }

  async function alternarPantallaV40(){
    const main=document.querySelector('main');if(!main) return;
    try{
      if(document.fullscreenElement) await document.exitFullscreen();
      else await main.requestFullscreen();
    }catch(e){if(typeof mostrarFallo==='function') mostrarFallo('El navegador no permitió cambiar a pantalla completa: '+e.message);}
  }

  function crearUiV40(){
    const main=document.querySelector('main');if(!main||document.getElementById('map-tools-v40')) return;
    const tools=document.createElement('div');tools.id='map-tools-v40';tools.setAttribute('aria-label','Herramientas del mapa');
    const fs=document.createElement('button');fs.id='btn-fullscreen-v40';fs.className='map-tool-v40';fs.type='button';fs.addEventListener('click',alternarPantallaV40);
    tools.append(fs);main.appendChild(tools);
    const resumen=document.createElement('aside');resumen.id='resumen-ambito-v40';resumen.setAttribute('aria-label','Resumen del ámbito geográfico');main.appendChild(resumen);
    actualizarIconoPantallaV40();
  }

  function finalizarResultadoV40(data){
    if(!data) return;ultimoResultadoV40=data;
    const tools=document.getElementById('map-tools-v40');
    const cartografico=Boolean(data.geometria)&&!['matriz_od','torta','barras'].includes(data.tipo_visualizacion);
    tools?.classList.toggle('visible',cartografico);
    renderResumenV40(data);
    if(document.fullscreenElement) actualizarEtiquetasFullscreenV40();
  }

  document.addEventListener('fullscreenchange',async()=>{
    actualizarIconoPantallaV40();
    document.getElementById('resumen-ambito-v40')?.classList.toggle('visible',!document.fullscreenElement&&Boolean((resultadoV40()?.resumen_ambito)||resumenFallbackV40(resultadoV40())));
    setTimeout(()=>mapa.invalidateSize(false),0);
    await actualizarEtiquetasFullscreenV40();
  });

  crearUiV40();

  // El flujo principal asigna resultadoActual y luego vuelve visible el panel de acciones.
  // El observador evita acoplar esta extensión a una versión específica de consultar().
  const acciones=document.getElementById('acciones-resultado');
  if(acciones){
    new MutationObserver(()=>{
      if(acciones.classList.contains('visible')) setTimeout(()=>finalizarResultadoV40(resultadoV40()),0);
    }).observe(acciones,{attributes:true,attributeFilter:['class']});
  }
})();
