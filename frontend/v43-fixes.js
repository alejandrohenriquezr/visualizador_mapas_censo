/* V43: distribución de tortas según la variable principal. */
(function instalarCorreccionesV43(){
  'use strict';
  if(window.__visorV43Instalado) return;
  window.__visorV43Instalado = true;

  const COLORES_V43 = ['#2f5d50','#b5652c','#5578a0','#8b6c8e','#9b927c'];

  function dimensionesV43(data){
    const directas = Array.isArray(data?.dimensiones) ? data.dimensiones : [];
    if(directas.length) return directas;
    const plan = data?.interpretacion?.plan_cruce || {};
    return Array.isArray(plan.dimensiones) ? plan.dimensiones : [];
  }

  function textoV43(valor){
    return String(valor ?? '').trim();
  }

  function codigoPrimeroV43(item){
    if(Array.isArray(item?.codigos) && item.codigos.length) return textoV43(item.codigos[0]);
    const codigo = textoV43(item?.codigo);
    return codigo.includes('|') ? codigo.split('|',1)[0] : codigo;
  }

  function etiquetaPrimeraV43(item, dimension){
    if(Array.isArray(item?.etiquetas) && item.etiquetas.length) return textoV43(item.etiquetas[0]);
    const compuesta = textoV43(item?.etiqueta);
    if(compuesta){
      const primera = compuesta.split(/\s*·\s*/)[0] || compuesta;
      const dosPuntos = primera.indexOf(':');
      if(dosPuntos >= 0) return primera.slice(dosPuntos + 1).trim();
      return primera;
    }
    return codigoPrimeroV43(item) || textoV43(dimension?.etiqueta || dimension?.variable);
  }

  function ordenNaturalCodigosV43(a,b){
    const na=Number(a), nb=Number(b);
    if(Number.isFinite(na) && Number.isFinite(nb)) return na-nb;
    return String(a).localeCompare(String(b),'es',{numeric:true,sensitivity:'base'});
  }

  function reagruparPrimeraDimensionV43(data){
    if(!data || data.tipo_visualizacion !== 'tortas_mapa' || !Array.isArray(data.datos)) return data;
    const dimensiones = dimensionesV43(data);
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
        const codigoCompuesto = textoV43(item?.codigo);
        if(codigoCompuesto.includes('|')) hayCruceCompleto = true;
        const codigo = codigoPrimeroV43(item);
        if(!codigo || codigo.toLowerCase()==='otros') continue;
        const valor = Number(item?.valor) || 0;
        conteos.set(codigo,(conteos.get(codigo)||0)+valor);
        totalesGlobales.set(codigo,(totalesGlobales.get(codigo)||0)+valor);
        if(!etiquetas.has(codigo)) etiquetas.set(codigo,etiquetaPrimeraV43(item,primera));
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
      principales = [...todos].sort(ordenNaturalCodigosV43);
    }else{
      principales = [...todos].sort((a,b)=>{
        const dif=(totalesGlobales.get(b)||0)-(totalesGlobales.get(a)||0);
        return dif || ordenNaturalCodigosV43(a,b);
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

  function etiquetaDimensionV43(data){
    const d=data?.dimension_torta || dimensionesV43(data)[0];
    let etiqueta=textoV43(d?.etiqueta || d?.variable || 'Variable principal');
    // Las descripciones oficiales largas se simplifican sólo para la leyenda.
    etiqueta=etiqueta.replace(/^\d+(?:\.\d+)?[a-z]?\.\s*/i,'').trim();
    return etiqueta;
  }

  function nivelPluralV43(data){
    const nivel=data?.nivel_geografico || data?.interpretacion?.nivel_geografico;
    return ({region:'regiones',provincia:'provincias',comuna:'comunas'})[nivel] || 'territorios';
  }

  function tituloTortaV43(data){
    const principal=etiquetaDimensionV43(data);
    const desc=textoV43(data?.interpretacion?.descripcion);
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
    return `Distribución según ${principal}, por ${nivelPluralV43(data)}.`;
  }

  function actualizarLeyendaV43(data){
    if(data?.tipo_visualizacion!=='tortas_mapa' || dimensionesV43(data).length<2) return;
    const titulo=document.getElementById('leyenda-titulo');
    if(titulo) titulo.textContent=tituloTortaV43(data);
    const lista=document.getElementById('leyenda-categorias');
    if(lista){
      lista.replaceChildren();
      (data.categorias_grafico||[]).forEach((categoria,indice)=>{
        const fila=document.createElement('li');
        const color=document.createElement('span');color.className='torta-color';color.style.background=COLORES_V43[indice%COLORES_V43.length];
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
      reagruparPrimeraDimensionV43(data);
      const salida=await pintarAnterior(data);
      actualizarLeyendaV43(data);
      return salida;
    };
    envoltura.__v42=true;
    window.pintarTortasMapa=envoltura;
  }

})();
