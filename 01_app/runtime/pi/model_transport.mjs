import contract from '../../config/model-contract.json' with {type:'json'};

const apis=new Set(contract.apis.map(item=>item.id));
// The declared API is executable configuration. Native providers retain their
// own headers/endpoint handling when that API belongs to their catalog. A user
// override uses Pi's corresponding API implementation, never another protocol.
export async function modelStream(model,provider){
 if(!apis.has(model.api))throw new Error('Unsupported model API');
 const nativeApis=new Set(provider?.getModels().map(item=>item.api));
 if(provider?.streamSimple&&nativeApis.has(model.api))return provider.streamSimple;
 return (await import(`@earendil-works/pi-ai/api/${model.api}`)).streamSimple;
}
