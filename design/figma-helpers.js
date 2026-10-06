const S={"boardId":"6:47","componentFrameId":"6:53","sections":{"Introduction":"6:48","Live overlays":"6:49","Companion windows":"6:50","Connection states":"6:51","Design notes":"6:52"},"collectionId":"VariableCollectionId:6:4","modeIds":{"Dark":"6:0"},"appleCollectionId":"VariableCollectionId:158c3760fc1910e82f0b41413d89c0fb0b20c306/4311:30","variables":{"color/surface/canvas":"VariableID:6:16","color/surface/panel":"VariableID:6:17","color/surface/raised":"VariableID:6:18","color/text/secondary":"VariableID:6:19","color/text/accent":"VariableID:6:20","color/text/success":"VariableID:6:21","color/text/warning":"VariableID:6:22","color/text/danger":"VariableID:6:23","color/stroke/separator":"VariableID:6:24","color/surface/selected":"VariableID:6:25","color/surface/information":"VariableID:6:26","color/text/primary":"VariableID:6:27","color/surface/window":"VariableID:6:28","space/4":"VariableID:6:29","space/8":"VariableID:6:30","space/12":"VariableID:6:31","space/16":"VariableID:6:32","space/20":"VariableID:6:33","space/24":"VariableID:6:34","space/32":"VariableID:6:35","space/48":"VariableID:6:36","radius/6":"VariableID:6:37","radius/10":"VariableID:6:38","radius/16":"VariableID:6:39","radius/20":"VariableID:6:40"},"primitiveIds":["VariableID:6:5","VariableID:6:6","VariableID:6:7","VariableID:6:8","VariableID:6:9","VariableID:6:10","VariableID:6:11","VariableID:6:12","VariableID:6:13","VariableID:6:14","VariableID:6:15"],"styles":{"body":"S:cdf6c668bb853046d5c23d0f3674ea1e608e856e,1:713","caption":"S:b2a0deca1cf308c745fa23647cef170f1394e5bd,","label":"S:a84a3553f739e57b38bb0d86812c3bc2186ec13a,","heading":"S:5d58bc93fe36714c392d95773020eaa7a9ba2588,","title":"S:cc0fec6b66be1850367a02708f4a8eff45410aee,","display":"S:10c8d4fbba69fe3365d59a2ef6ecf527c1373fe9,","metric":"S:a96cd019f51358ecc9205247609eda98ff07dc6b,"},"createdNodeIds":["6:47","6:48","6:49","6:50","6:51","6:52","6:53"]};
const page=await figma.getNodeByIdAsync('0:1');await figma.setCurrentPageAsync(page);
const values=await Promise.all(Object.values(S.variables).map(id=>figma.variables.getVariableByIdAsync(id)));
const V=Object.fromEntries(Object.keys(S.variables).map((k,i)=>[k,values[i]]));
const locals=await figma.getLocalTextStylesAsync();
const bodyStyle=await figma.importStyleByKeyAsync('cdf6c668bb853046d5c23d0f3674ea1e608e856e');
const styles=Object.keys(S.styles).map(k=>k==='body'?bodyStyle:locals.find(s=>s.name==='BG Tracker/'+k));
const TS=Object.fromEntries(Object.keys(S.styles).map((k,i)=>[k,styles[i]]));
await Promise.all([...Object.values(TS).map(s=>s.fontName),...['Regular','Medium','Semibold','Bold'].map(style=>({family:'SF Pro',style})),{family:'SF Pro',style:'Semibold',variationSettings:{wght:590,wdth:100}}].map(f=>figma.loadFontAsync(f)));
const allIds=n=>[n.id,...('children' in n?n.children.flatMap(allIds):[])];
const before=new Set(allIds(page));
const fill=(n,key)=>{n.fills=[figma.variables.setBoundVariableForPaint({type:'SOLID',color:{r:0,g:0,b:0}},'color',V[key])];};
function al(parent,name,w,dir='VERTICAL',gap=8,pad=0,surface){
 const f=figma.createAutoLayout(dir);f.name=name;f.resize(w,24);f.layoutSizingHorizontal='FIXED';f.layoutSizingVertical='HUG';f.fills=[];f.itemSpacing=gap;f.counterAxisAlignItems=dir==='HORIZONTAL'?'CENTER':'MIN';
 for(const d of ['Top','Bottom','Left','Right']){f['padding'+d]=pad;if(V['space/'+pad])f.setBoundVariable('padding'+d,V['space/'+pad]);}
 if(V['space/'+gap])f.setBoundVariable('itemSpacing',V['space/'+gap]);
 if(surface)fill(f,'color/surface/'+surface);
 if(parent)parent.appendChild(f);return f;
}
function fillWidth(n){n.layoutSizingHorizontal='FILL';return n;}
function radius(n,size=10){n.cornerRadius=size;n.setBoundVariable('cornerRadius',V['radius/'+size]);}
async function txt(parent,name,value,role='body',color='primary',width){
 const t=figma.createText();t.name=name;t.fontName={family:TS[role].fontName.family,style:TS[role].fontName.style};await t.setTextStyleIdAsync(S.styles[role]);t.characters=value;fill(t,'color/text/'+color);
 if(width){t.textAutoResize='HEIGHT';t.resize(width,t.height);}else t.textAutoResize='WIDTH_AND_HEIGHT';
 parent.appendChild(t);return t;
}
function divider(parent,w){const d=figma.createRectangle();d.name='Separator';d.resize(w,1);fill(d,'color/surface/raised');parent.appendChild(d);return d;}
function prop(c,node,label){const k=c.addComponentProperty(label,'TEXT',node.characters);node.componentPropertyReferences={characters:k};return k;}
function instance(parent,c,name,props={}){const i=c.createInstance();i.name=name;if(Object.keys(props).length)i.setProperties(props);parent.appendChild(i);return i;}
function border(n){n.strokes=[figma.variables.setBoundVariableForPaint({type:'SOLID',color:{r:0,g:0,b:0}},'color',V['color/stroke/separator'])];n.strokeWeight=1;}
const created=()=>allIds(page).filter(id=>!before.has(id));
