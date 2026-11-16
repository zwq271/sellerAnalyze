const $ = id => document.getElementById(id);
const state = {country:'US', category:'', subcategory:'', page:1, sort:'published_at', order:'desc', selected:new Set(), items:[], config:null, total:0};
const esc = x => String(x ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count = n => n == null ? '—' : new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2,notation:n>=10000?'compact':'standard'}).format(n);
const money = (n,c='USD') => n == null ? '—' : new Intl.NumberFormat('zh-CN',{style:'currency',currency:/^[A-Z]{3}$/.test(c)?c:'USD',maximumFractionDigits:2}).format(n);
const date = x => x ? new Date(x).toLocaleString('zh-CN',{hour12:false}) : '—';
const rate = x => x == null ? '—' : `${Number(x).toFixed(2)}%`;
const market = r => r.country==='UNKNOWN' ? `${r.target_market||'未知'} 目标 · 销售市场未核验` : r.country;
let collectorDone = '', collectBusy = false;
let toastTimer, queryVersion=0, toastId;
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':state.config.token},body:JSON.stringify(body)}:{});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;}
function params(){
  const p=new URLSearchParams({country:state.country,category:state.category,subcategory:state.subcategory,page:state.page,sort:state.sort,order:state.order});
  for(const id of ['q','min_views','min_sales','min_revenue','from','to'])if($(id).value)p.set(id,$(id).value);
  for(const id of ['commerce','products'])if($(id).checked)p.set(id,'true');
  for(const id of ['from','to'])if($(id).value){const d=new Date($(id).value+'T00:00:00');if(id==='to')d.setDate(d.getDate()+1);p.set(id+'_utc',d.toISOString());}
  return p;
}
function chips(id,values,selected,onChange){$(id).innerHTML=[['','全部'],...values.map(v=>[v,v])].map(([v,label])=>`<button class="chip ${selected===v?'selected':''}" data-value="${esc(v)}">${esc(label)}</button>`).join('');$(id).onclick=e=>{const b=e.target.closest('button');if(b)onChange(b.dataset.value);};}
function renderCategories(extra=[]){
  chips('categories',[...new Set([...Object.keys(state.config.categories),...extra])],state.category,v=>{state.category=v;state.subcategory='';state.page=1;state.selected.clear();renderCategories(extra);load();});
  const subs=[...new Set([...(state.config.categories[state.category]||[]),...(state.subcategories?.[state.category]||[])])];
  $('subcategories').closest('.filter-row').hidden=!state.category||!subs.length;
  chips('subcategories',subs,state.subcategory,v=>{state.subcategory=v;state.page=1;state.selected.clear();renderCategories(extra);load();});
}
function cover(url,product=false){return url?`<img class="cover ${product?'product-cover':''}" src="${esc(url)}" loading="lazy" referrerpolicy="no-referrer" alt="${product?'商品图片':'视频封面'}">`:`<span class="cover ${product?'product-cover':''}">${product?'◇':'▷'}</span>`;}
function selection(){const n=state.selected.size;$('download-selected').disabled=!n||!state.config.downloader_ready;$('selection-info').textContent=n?`已选 ${n} 条 · 导出将仅包含所选视频`:'未选择时导出全部筛选结果';$('select-all').checked=!!state.items.length&&state.items.every(r=>state.selected.has(r.video_id));$('select-all').indeterminate=state.items.some(r=>state.selected.has(r.video_id))&&!$('select-all').checked;}
async function load(){
  const version=++queryVersion;
  try{
    const result=await api('/api/videos?'+params());if(version!==queryVersion)return;
    state.items=result.items;state.total=result.filtered;state.subcategories=result.subcategories;
    renderCategories(result.categories);
    $('result-count').textContent=result.filtered;$('page-info').textContent=`筛选 ${result.filtered} 条 / 本地共 ${result.total} 条`;
    $('page-number').textContent=state.page;$('prev').disabled=state.page===1;$('next').disabled=state.page*30>=result.filtered;
    $('empty').hidden=!!result.items.length;
    $('empty').querySelector('h3').textContent=result.total?'没有符合条件的视频':'视频库准备好了，等待第一批数据';
    $('rows').innerHTML=result.items.map(r=>{
      const p=r.products[0];
      return `<tr><td><input type="checkbox" data-select="${esc(r.video_id)}" aria-label="选择 ${esc(r.title||r.video_id)}" ${state.selected.has(r.video_id)?'checked':''}></td><td><div class="media-cell">${cover(r.cover_url)}<div><a href="${esc(r.video_url||'#')}" target="_blank" rel="noopener noreferrer" class="cell-title">${esc(r.title||r.video_id)}</a><div class="cell-meta">${esc(r.author||'达人未知')} · ${r.duration==null?'时长未知':r.duration+' 秒'}<br>${esc(market(r))}<br>${esc(r.category)}${r.category_evidence?' · 关键词推断':''}${r.subcategory?' / '+esc(r.subcategory):''}</div><span class="tag">${r.is_commerce===true?'带货标记':r.is_commerce===false?'非带货':'带货状态未知'}</span></div></div></td><td>${p?`<div class="media-cell">${cover(p.image,true)}<div><span class="cell-title">${esc(p.name||p.id||'未命名商品')}</span><div class="cell-meta">${esc(money(p.price,p.currency))}${r.products.length>1?' · 共 '+r.products.length+' 件商品':''}</div></div></div>`:'<span class="cell-meta">未获取关联商品</span>'}</td><td><span class="metric sales">${count(r.estimated_sales)}</span></td><td><span class="metric">${esc(money(r.estimated_revenue,r.currency))}</span></td><td><span class="metric">${esc(date(r.published_at))}</span></td><td><span class="metric">${count(r.views)}</span></td><td><span class="metric">${rate(r.engagement_rate)}</span></td><td><div class="row-actions"><button data-detail="${esc(r.video_id)}">查看详情</button><button data-download="${esc(r.video_id)}" ${!state.config.downloader_ready?'disabled':''}>↓ 下载视频</button></div></td></tr>`;
    }).join('');selection();
  }catch(e){toast(e.message);}
}
function detail(vid){const r=state.items.find(r=>r.video_id===vid);if(!r)return;const fields=[['发布时间',date(r.published_at)],['目标 / 销售市场',market(r)],['类目',r.category],['类目判断依据',r.category_evidence||'来源提供'],['播放量',count(r.views)],['预估视频销量',count(r.estimated_sales)],['预估销售额',money(r.estimated_revenue,r.currency)],['视频互动率',rate(r.engagement_rate)],['广告观看占比',rate(r.ad_view_ratio)],['统计周期',r.metrics_period||'来源未提供'],['采集时间',date(r.collected_at)]];
  $('detail-content').innerHTML=`<h3>${esc(r.title||r.video_id)}</h3><p><a href="${esc(r.video_url)}" target="_blank" rel="noopener noreferrer">打开 TikTok 原视频 ↗</a></p><dl class="detail-grid">${fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl><h3>关联商品 · ${r.products.length}</h3>${r.products.map(p=>`<div class="product-detail">${p.image?`<img src="${esc(p.image)}" referrerpolicy="no-referrer" alt="商品图片">`:''}<div><strong>${esc(p.name||p.id)}</strong><p>${esc(money(p.price,p.currency))} · ${esc(p.shop||'店铺未提供')}<br>商品 ID：${esc(p.id||'未提供')}<br>关联依据：${esc(p.evidence)}<br>来源：${esc(p.source)}</p>${p.url?`<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">打开商品页面 ↗</a>`:''}</div></div>`).join('')||'<p class="cell-meta">当前没有商品关联信息。</p>'}<div class="detail-source">数据来源：${esc(r.source)}<br>带货依据：${esc(r.commerce_evidence||'来源未提供')}<br>${esc(r.market_evidence||'')}<br>搜索词：${esc(r.search_query||'未提供')}<br>预估销售指标按来源口径展示，缺失值不视为零。${Object.keys(r.field_sources||{}).length?'<br>字段来源：'+esc(JSON.stringify(r.field_sources)):''}</div>`;$('details-dialog').showModal();}
async function download(ids){try{const r=await api('/api/download',{ids});toast(`已加入 ${r.task_ids.length} 个下载任务`);showView('tasks');}catch(e){toast(e.message);}}
function showView(view){$('library-view').hidden=view!=='library';$('tasks-view').hidden=view!=='tasks';$('page-name').textContent=view==='library'?'发现带货视频':'下载任务';document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));if(view==='tasks')loadTasks();}
async function loadTasks(){try{const r=await api('/api/tasks');$('task-count').textContent=r.items.filter(t=>['queued','running'].includes(t.status)).length;$('download-status').textContent=state.config.downloader_ready?'下载文件和关联商品元数据会保存在本地 downloads 文件夹。带货视频可能因来源限制无法下载。':'当前 Python 环境尚未安装可用的下载组件；请查看 README.txt 安装说明。';$('tasks').innerHTML=r.items.map(t=>`<article class="task"><div><strong>视频 ${esc(t.video_id)}</strong><p>${esc(date(t.created_at))}${t.error?'<br>'+esc(t.error):''}</p></div><div><span class="task-state ${esc(t.status)}">${({queued:'等待下载',running:'正在下载',done:'下载完成',failed:'下载失败'})[t.status]||esc(t.status)}</span>${t.status==='done'?`<p><a href="/api/file/${esc(t.id)}">保存视频到电脑 ↓</a></p>`:''}${t.status==='failed'?`<p><button class="text-button" data-retry="${esc(t.video_id)}">重新下载</button></p>`:''}</div></article>`).join('')||'<div class="empty"><div class="empty-icon">↓</div><h3>还没有下载任务</h3><p>在视频列表选择视频后，点击“下载所选视频”。</p></div>';}catch(e){toast(e.message);}}
async function refreshCollector(){
  try{
    const job=await api('/api/collector');
    collectBusy=['running','awaiting_login','cancelling'].includes(job.status);
    $('collect-start').disabled=collectBusy||!state.config.live_search_ready;
    $('collect-login').disabled=collectBusy||!state.config.live_search_ready;
    $('collect-finish').hidden=job.status!=='awaiting_login';
    $('collect-cancel').hidden=!collectBusy;
    $('collect-status').textContent=job.status==='idle'?'独立浏览器会话保存在本机；可先尝试采集，需要登录时再完成登录。':job.message;
    $('collect-status').dataset.status=job.status;
    if(job.status==='done'&&job.id!==collectorDone){
      collectorDone=job.id;
      if(job.imported){state.page=1;state.selected.clear();$('commerce').checked=false;await load();}
      toast(job.message);
    }
  }catch(e){$('collect-status').textContent=e.message;}
}
async function startCollection(mode){
  if(collectBusy)return;
  $('collect-start').disabled=$('collect-login').disabled=true;
  try{
    await api('/api/collect',{mode,query:$('collect-q').value,category:state.category,subcategory:state.subcategory,market:state.country||'US',limit:Number($('collect-limit').value)});
    await refreshCollector();
  }catch(e){toast(e.message);$('collect-start').disabled=$('collect-login').disabled=false;}
}
function parseCSV(text){const rows=[];let row=[],cell='',quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(!quoted&&cell.length){throw Error('CSV 引号位置无效');}else quoted=!quoted;}else if(c===','&&!quoted){row.push(cell);cell='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(Boolean))rows.push(row);row=[];cell='';}else cell+=c;}if(quoted)throw Error('CSV 引号未闭合');row.push(cell);if(row.some(Boolean))rows.push(row);if(!rows.length)throw Error('文件没有内容');const keys=rows.shift().map(k=>k.trim());if(new Set(keys).size!==keys.length)throw Error('CSV 表头包含重复字段');return rows.map((values,i)=>{if(values.length!==keys.length)throw Error(`CSV 第 ${i+2} 行列数与表头不符`);return Object.fromEntries(keys.map((k,i)=>[k,values[i]??'']));});}
function saveFile(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
$('import-open').onclick=$('empty-import').onclick=()=>$('import-dialog').showModal();
$('source-info').onclick=()=>$('source-dialog').showModal();
$('collect-start').onclick=()=>startCollection('search');
$('collect-login').onclick=()=>startCollection('login');
$('collect-q').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();startCollection('search');}};
for(const [id,action] of [['collect-finish','finish'],['collect-cancel','cancel']])$(id).onclick=async()=>{try{await api('/api/collector/action',{action});await refreshCollector();}catch(e){toast(e.message);}};
$('filters').onsubmit=e=>{e.preventDefault();if($('from').value&&$('to').value&&$('from').value>$('to').value)return toast('结束日期不能早于起始日期');state.page=1;state.selected.clear();load();};
$('countries').onclick=e=>{const b=e.target.closest('button');if(!b)return;state.country=b.dataset.value;state.page=1;state.selected.clear();document.querySelectorAll('#countries button').forEach(x=>x.classList.toggle('selected',x===b));load();};
for(const id of ['commerce','products'])$(id).onchange=()=>{state.page=1;state.selected.clear();load();};
$('reset').onclick=()=>{$('filters').reset();state.category='';state.subcategory='';state.page=1;state.sort='published_at';state.order='desc';state.selected.clear();load();};
document.querySelectorAll('[data-sort]').forEach(b=>b.onclick=()=>{state.order=state.sort===b.dataset.sort&&state.order==='desc'?'asc':'desc';state.sort=b.dataset.sort;state.page=1;document.querySelectorAll('[data-sort]').forEach(x=>{x.textContent=x.textContent.replace(/[↕↑↓]/g,'')+(x===b?(state.order==='asc'?'↑':'↓'):'↕');});load();});
$('rows').onchange=e=>{if(e.target.dataset.select){const id=e.target.dataset.select;e.target.checked?state.selected.add(id):state.selected.delete(id);selection();}};
$('rows').onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.detail)detail(b.dataset.detail);if(b.dataset.download)download([b.dataset.download]);};
$('select-all').onchange=e=>{state.items.forEach(r=>e.target.checked?state.selected.add(r.video_id):state.selected.delete(r.video_id));document.querySelectorAll('[data-select]').forEach(x=>x.checked=e.target.checked);selection();};
$('download-selected').onclick=()=>download([...state.selected]);
for(const format of ['json','csv'])$('export-'+format).onclick=()=>{const p=params();p.set('format',format);if(state.selected.size)p.set('ids',[...state.selected].join(','));window.location.href='/api/export?'+p;};
$('prev').onclick=()=>{if(state.page>1){state.page--;load();}};$('next').onclick=()=>{if(state.page*30<state.total){state.page++;load();}};
$('refresh-tasks').onclick=loadTasks;$('tasks').onclick=e=>{if(e.target.dataset.retry)download([e.target.dataset.retry]);};
$('import-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>10*1024*1024)throw Error('文件超过 10MB');$('import-text').value=await file.text();$('import-error').textContent='';}catch(e){$('import-error').textContent=e.message;}};
$('template').onclick=()=>saveFile('video-template.json',JSON.stringify([{video_id:'请替换为真实视频ID',video_url:'https://www.tiktok.com/@账号/video/视频ID',title:'',author:'',country:'US',category:'美妆个护',subcategory:'护肤',is_commerce:null,commerce_evidence:'',published_at:'',views:null,likes:null,comments:null,estimated_sales:null,estimated_revenue:null,engagement_rate:null,metrics_period:'',source:'请填写真实数据来源',products:[{id:'',name:'',url:'',image:'',price:null,currency:'USD',shop:'',evidence:''}]}],null,2),'application/json');
$('import-submit').onclick=async()=>{const button=$('import-submit');button.disabled=true;try{const text=$('import-text').value.replace(/^\uFEFF/,'').trim();const parsed=text.startsWith('[')||text.startsWith('{')?JSON.parse(text):parseCSV(text);const rows=Array.isArray(parsed)?parsed:parsed.items||parsed.rows;if(!Array.isArray(rows)||!rows.length)throw Error('没有可导入的数据，请使用 JSON 数组或带表头的 CSV');const result=await api('/api/import',{rows});$('import-dialog').close();$('import-text').value='';$('import-error').textContent='';state.selected.clear();state.page=1;toast(`已保存 ${result.imported} 条视频`);await load();}catch(e){$('import-error').textContent=e.message;}finally{button.disabled=false;}};
async function init(){try{state.config=await api('/api/config');renderCategories();await load();await loadTasks();await refreshCollector();setInterval(()=>{if(!$('tasks-view').hidden)loadTasks();refreshCollector();},2500);}catch(e){toast('无法连接本地服务：'+e.message);}}
init();
