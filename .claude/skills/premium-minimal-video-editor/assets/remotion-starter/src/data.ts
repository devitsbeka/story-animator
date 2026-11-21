// Replace with real approved plan; all visual timings are in frame units.
// Demo content is not a finished edit or a reconstruction of tutorial references.
export type Family = 'AROLL'|'P01'|'P02'|'P03'|'P04'|'P05'|'P06'|'P07'|'P08'|'P09'|'P10';
export type Scene = {id:string; type:Family; duration:number; text:string; emphasis?:string; image?:string; video?:string; detail?:string; values?:number[]};
export const FPS=30;
export const WIDTH=1080;
export const HEIGHT=1920;
export const SCENES:Scene[]=[
 {id:'S001',type:'AROLL',duration:65,text:'Four career patterns',emphasis:'FOUR',detail:'Demo placeholder: replace with a licensed speaker clip.'},
 {id:'S002',type:'P10',duration:105,text:'Up and up and up',values:[1,2,4,7,10]},
 {id:'S003',type:'P04',duration:75,text:'Calling · Agility · Courage',emphasis:'Courage'},
 {id:'S004',type:'P06',duration:80,text:'The business of life',emphasis:'life'},
];
export const DURATION=SCENES.reduce((sum,s)=>sum+s.duration,0);
