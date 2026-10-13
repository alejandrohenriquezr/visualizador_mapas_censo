/* V42: variable principal de tortas + exportación PNG con marcadores normalizados. */
(function instalarCorreccionesV42(){
  'use strict';
  if(window.__visorV42Instalado) return;
  window.__visorV42Instalado = true;

  const COLORES_V42 = ['#2f5d50','#b5652c','#5578a0','#8b6c8e','#9b927c'];

  function dimensionesV42(data){
    const directas = Array.isArray(data?.dimensiones) ? data.dimensiones : [];
    if(directas.length) return directas;
    const plan = data?.interpretacion?.plan_cruce || {};
    return Array.isArray(plan.dimensiones) ? plan.dimensiones : [];
  }

  function textoV42(valor){
    return String(valor ?? '').trim();
  }

  function codigoPrimeroV42(item){
    if(Array.isArray(item?.codigos) && item.codigos.length) return textoV42(item.codigos[0]);
    const codigo = textoV42(item?.codigo);
    return codigo.includes('|') ? codigo.split('|',1)[0] : codigo;
  }

  function etiquetaPrimeraV42(item, dimension){
    if(Array.isArray(item?.etiquetas) && item.etiquetas.length) return textoV42(item.etiquetas[0]);
    const compuesta = textoV42(item?.etiqueta);
    if(compuesta){
      const primera = compuesta.split(/\s*·\s*/)[0] || compuesta;
      const dosPuntos = primera.indexOf(':');
      if(dosPuntos >= 0) return primera.slice(dosPuntos + 1).trim();
      return primera;
    }
    return codigoPrimeroV42(item) || textoV42(dimension?.etiqueta || dimension?.variable);
  }

  function ordenNaturalCodigosV42(a,b){
    const na=Number(a), nb=Number(b);
    if(Number.isFinite(na) && Number.isFinite(nb)) return na-nb;
    return String(a).localeCompare(String(b),'es',{numeric:true,sensitivity:'base'});
  }

  function reagruparPrimeraDimensionV42(data){
    if(!data || data.tipo_visualizacion !== 'tortas_mapa' || !Array.isArray(data.datos)) return data;
    const dimensiones = dimensionesV42(data);
    if(dimensiones.length < 2) return data;
    const primera = dimensiones[0];

    const totalesGlobales = new Map();
    const etiquetas = new Map();
    const porTerritorio = new Map();
    let hayCruceCompleto = false;

    for(const territorio of data.datos){
      const completa = Array.isArray(territorio?.distribucion_completa) && territorio.distribucion_completa.length
        ? territorio.distribucion_completa
        : (Array.isArray(territorio?.distribucion) ? territorio.distribucion : []);
      const conteos = new Map();
      for(const item of completa){
        const codigoCompuesto = textoV42(item?.codigo);
        if(codigoCompuesto.includes('|')) hayCruceCompleto = true;
        const codigo = codigoPrimeroV42(item);
        if(!codigo || codigo.toLowerCase()==='otros') continue;
        const valor = Number(item?.valor) || 0;
        conteos.set(codigo,(conteos.get(codigo)||0)+valor);
        totalesGlobales.set(codigo,(totalesGlobales.get(codigo)||0)+valor);
        if(!etiquetas.has(codigo)) etiquetas.set(codigo,etiquetaPrimeraV42(item,primera));
      }
      porTerritorio.set(String(territorio?.codigo ?? ''),conteos);
    }

    // Si no hay material de cruce, no toca una distribución univariada legítima.
    if(!hayCruceCompleto || !totalesGlobales.size) return data;

    let todos = [...totalesGlobales.keys()];
    // Para dimensiones pequeñas (sexo, condición binaria, etc.) conserva el orden
    // natural de códigos; para dimensiones extensas mantiene el criterio del visor:
    // cuatro categorías principales + Otros.
    let principales;
    if(todos.length <= 4){
      principales = [...todos].sort(ordenNaturalCodigosV42);
    }else{
      principales = [...todos].sort((a,b)=>{
        const dif=(totalesGlobales.get(b)||0)-(totalesGlobales.get(a)||0);
        return dif || ordenNaturalCodigosV42(a,b);
      }).slice(0,4);
    }
    const agruparOtros = todos.length > principales.length;

    data.categorias_grafico = principales.map(codigo=>({
      codigo,
      etiqueta: etiquetas.get(codigo) || codigo
    }));
    if(agruparOtros) data.categorias_grafico.push({codigo:'otros',etiqueta:'Otros'});

    for(const territorio of data.datos){
      const conteos = porTerritorio.get(String(territorio?.codigo ?? '')) || new Map();
      const total = [...conteos.values()].reduce((a,b)=>a+b,0);
      const distribucion = principales.map(codigo=>{
        const valor=conteos.get(codigo)||0;
        return {
          codigo,
          etiqueta:etiquetas.get(codigo)||codigo,
          valor,
          porcentaje:total ? 100*valor/total : null
        };
      });
      if(agruparOtros){
        const otros=[...conteos.entries()]
          .filter(([codigo])=>!principales.includes(codigo))
          .reduce((s,[,valor])=>s+valor,0);
        distribucion.push({
          codigo:'otros',etiqueta:'Otros',valor:otros,
          porcentaje:total ? 100*otros/total : null
        });
      }
      territorio.distribucion = distribucion;
      territorio.total = total;
    }

    data.dimensiones = dimensiones;
    data.torta_primera_dimension = true;
    data.dimension_torta = primera;
    return data;
  }

  function etiquetaDimensionV42(data){
    const d=data?.dimension_torta || dimensionesV42(data)[0];
    let etiqueta=textoV42(d?.etiqueta || d?.variable || 'Variable principal');
    // Las descripciones oficiales largas se simplifican sólo para la leyenda.
    etiqueta=etiqueta.replace(/^\d+(?:\.\d+)?[a-z]?\.\s*/i,'').trim();
    return etiqueta;
  }

  function nivelPluralV42(data){
    const nivel=data?.nivel_geografico || data?.interpretacion?.nivel_geografico;
    return ({region:'regiones',provincia:'provincias',comuna:'comunas'})[nivel] || 'territorios';
  }

  function tituloTortaV42(data){
    const principal=etiquetaDimensionV42(data);
    const desc=textoV42(data?.interpretacion?.descripcion);
    if(desc){
      // Sustituye exclusivamente el tramo de dimensiones y conserva universo/filtro.
      const reemplazado=desc.replace(
        /\s+según\s+[^,]+(?=,\s+según\s+(?:regiones|provincias|comunas|territorios)\b)/i,
        ` según ${principal}`
      );
      if(reemplazado !== desc) return reemplazado;
      const reemplazadoPor=desc.replace(
        /\s+(?:por|según)\s+[^,.]+(?=\s+(?:por|según)\s+(?:regiones|provincias|comunas)\b)/i,
        ` según ${principal}`
      );
      if(reemplazadoPor !== desc) return reemplazadoPor;
    }
    return `Distribución según ${principal}, por ${nivelPluralV42(data)}.`;
  }

  function actualizarLeyendaV42(data){
    if(data?.tipo_visualizacion!=='tortas_mapa' || dimensionesV42(data).length<2) return;
    const titulo=document.getElementById('leyenda-titulo');
    if(titulo) titulo.textContent=tituloTortaV42(data);
    const lista=document.getElementById('leyenda-categorias');
    if(lista){
      lista.replaceChildren();
      (data.categorias_grafico||[]).forEach((categoria,indice)=>{
        const fila=document.createElement('li');
        const color=document.createElement('span');color.className='torta-color';color.style.background=COLORES_V42[indice%COLORES_V42.length];
        const etiqueta=document.createElement('span');etiqueta.textContent=categoria?.etiqueta||categoria?.codigo||'';
        fila.append(color,etiqueta);lista.appendChild(fila);
      });
    }
  }

  // Se instala DESPUÉS de V36/V40/V41. Así, incluso una respuesta aprobada antigua
  // se normaliza por la primera dimensión antes de que V36 intente compactarla.
  const pintarAnterior=window.pintarTortasMapa;
  if(typeof pintarAnterior==='function' && !pintarAnterior.__v42){
    const envoltura=async function(data){
      reagruparPrimeraDimensionV42(data);
      const salida=await pintarAnterior(data);
      actualizarLeyendaV42(data);
      return salida;
    };
    envoltura.__v42=true;
    window.pintarTortasMapa=envoltura;
  }

  // -----------------------------------------------------------------------
  // PNG: html2canvas puede interpretar de forma distinta los translate3d de
  // Leaflet. Se conserva exactamente la vista actual y, en el CLON usado para
  // exportar, se reemplaza el marker-pane por una capa absoluta calculada desde
  // getBoundingClientRect(). Polígonos, tiles y marcadores quedan en el mismo
  // sistema de coordenadas sin modificar el mapa que ve el usuario.
  // -----------------------------------------------------------------------
  function marcadoresPantallaV42(){
    const mapaEl=document.getElementById('mapa');
    if(!mapaEl) return [];
    const mr=mapaEl.getBoundingClientRect();
    return [...mapaEl.querySelectorAll('.leaflet-marker-pane .leaflet-marker-icon')]
      .filter(el=>{
        const s=getComputedStyle(el);
        return s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity||1)>0;
      })
      .map(el=>{
        const r=el.getBoundingClientRect();
        return {
          html:el.outerHTML,
          left:r.left-mr.left,
          top:r.top-mr.top,
          width:r.width,
          height:r.height,
          z:getComputedStyle(el).zIndex || 'auto',
          opacity:getComputedStyle(el).opacity || '1'
        };
      });
  }

  function normalizarMarcadoresClonV42(doc,snapshots){
    const mapaClon=doc.getElementById('mapa');
    if(!mapaClon) return;
    mapaClon.querySelectorAll('.leaflet-marker-pane').forEach(p=>p.style.visibility='hidden');
    const overlay=doc.createElement('div');
    overlay.className='export-marker-overlay-v42';
    Object.assign(overlay.style,{
      position:'absolute',left:'0',top:'0',right:'0',bottom:'0',
      overflow:'hidden',pointerEvents:'none',zIndex:'650'
    });
    for(const snap of snapshots){
      const tpl=doc.createElement('template');
      tpl.innerHTML=snap.html.trim();
      const el=tpl.content.firstElementChild;
      if(!el) continue;
      Object.assign(el.style,{
        position:'absolute',
        left:`${snap.left}px`,top:`${snap.top}px`,
        transform:'none',margin:'0',
        width:`${snap.width}px`,height:`${snap.height}px`,
        zIndex:snap.z,opacity:snap.opacity
      });
      overlay.appendChild(el);
    }
    mapaClon.appendChild(overlay);
  }

  async function cargarHtml2CanvasV42(){
    if(window.html2canvas) return window.html2canvas;
    return new Promise((resolve,reject)=>{
      const existente=document.querySelector('script[src*="html2canvas"]');
      if(existente){
        existente.addEventListener('load',()=>window.html2canvas?resolve(window.html2canvas):reject(new Error('html2canvas no disponible.')),{once:true});
        existente.addEventListener('error',()=>reject(new Error('No se pudo cargar html2canvas.')),{once:true});
        setTimeout(()=>{if(window.html2canvas) resolve(window.html2canvas);},0);
        return;
      }
      const s=document.createElement('script');
      s.src='https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
      s.crossOrigin='anonymous';
      s.onload=()=>window.html2canvas?resolve(window.html2canvas):reject(new Error('html2canvas no disponible.'));
      s.onerror=()=>reject(new Error('No se pudo cargar el componente PNG.'));
      document.head.appendChild(s);
    });
  }

  async function esperarTilesV42(timeoutMs=2500){
    const inicio=Date.now();
    while(Date.now()-inicio<timeoutMs){
      const tiles=[...document.querySelectorAll('#mapa img.leaflet-tile')].filter(img=>getComputedStyle(img).visibility!=='hidden');
      if(!tiles.length || tiles.every(img=>img.complete && img.naturalWidth>0)) return;
      await new Promise(r=>setTimeout(r,80));
    }
  }

  async function guardarPngV42(){
    const main=document.querySelector('main');
    if(!main) return;
    const boton=document.getElementById('btn-save-png-v40');
    if(boton) boton.disabled=true;
    document.body.classList.add('exportando-v40','exportando-v41','exportando-v42');
    try{
      if(document.body.classList.contains('v41-piramide-activa')){
        throw new Error('Vuelve a la pestaña Mapa antes de guardar la imagen.');
      }
      // V42 NO ejecuta fitBounds: captura la vista ya dibujada. Reencuadrar justo
      // antes de html2canvas era lo que dejaba marker-pane y polygon-pane desfasados.
      try{ if(typeof mapa!=='undefined' && mapa?.invalidateSize) mapa.invalidateSize(false); }catch(_e){}
      await esperarTilesV42();
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const snapshots=marcadoresPantallaV42();
      const h2c=await cargarHtml2CanvasV42();
      const rect=main.getBoundingClientRect();
      const canvas=await h2c(main,{
        useCORS:true,allowTaint:false,backgroundColor:'#f6f3ec',scale:2,logging:false,
        width:Math.max(1,Math.round(rect.width)),height:Math.max(1,Math.round(rect.height)),
        onclone:doc=>normalizarMarcadoresClonV42(doc,snapshots)
      });
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      if(!blob) throw new Error('No fue posible construir el archivo PNG.');
      const now=new Date(), pad=n=>String(n).padStart(2,'0');
      const nombre=`mapa_censo_${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.png`;
      const url=URL.createObjectURL(blob);const a=document.createElement('a');
      a.href=url;a.download=nombre;a.style.display='none';document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1200);
    }catch(e){
      const msg='No se pudo exportar el mapa a PNG. '+(e?.message||'');
      try{ if(typeof mostrarFallo==='function') mostrarFallo(msg); else window.alert(msg); }
      catch(_e){ window.alert(msg); }
    }finally{
      document.body.classList.remove('exportando-v40','exportando-v41','exportando-v42');
      if(boton) boton.disabled=false;
    }
  }

  const guardarAnterior=document.getElementById('btn-save-png-v40');
  if(guardarAnterior && guardarAnterior.dataset.v42!=='1'){
    const clon=guardarAnterior.cloneNode(true);
    clon.dataset.v42='1';
    guardarAnterior.replaceWith(clon);
    clon.addEventListener('click',event=>{
      event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
      guardarPngV42();
    },true);
  }
})();
