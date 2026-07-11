const DIVIDEND_EMPIRE_DEFAULT_SETTINGS={
  totalAssets:42000000,
  investedPrincipal:33500000,
  annualLivingCost:3600000,
  targetAssetAt60:200000000,
  milestones:[
    {age:45,amount:50000000},
    {age:50,amount:100000000},
    {age:55,amount:140000000},
    {age:60,amount:200000000}
  ],
  dividendLifestyleGoals:[
    {amount:100000,label:"Apple製品や家電"},
    {amount:300000,label:"年間のサウナ・外食費"},
    {amount:500000,label:"F1観戦や国内旅行"},
    {amount:1000000,label:"大型旅行や趣味費"},
    {amount:3000000,label:"生活費の大部分"},
    {amount:6000000,label:"配当生活ライン"}
  ]
};

const DIVIDEND_EMPIRE_DEFAULT_HOLDINGS=[
  {code:"7203",name:"トヨタ自動車",sector:"自動車",shares:1200,acquisitionPrice:2450,currentPrice:3100,annualDividendPerShare:75,benefitFaceValue:0,benefitUsageRate:0,purpose:"安定",status:"一軍"},
  {code:"6758",name:"ソニーグループ",sector:"電機・エンタメ",shares:300,acquisitionPrice:11800,currentPrice:14200,annualDividendPerShare:100,benefitFaceValue:0,benefitUsageRate:0,purpose:"成長",status:"成長枠"},
  {code:"7751",name:"キヤノン",sector:"精密機器",shares:500,acquisitionPrice:3600,currentPrice:4300,annualDividendPerShare:150,benefitFaceValue:0,benefitUsageRate:0,purpose:"配当",status:"一軍"},
  {code:"9432",name:"NTT",sector:"通信",shares:8000,acquisitionPrice:145,currentPrice:165,annualDividendPerShare:5.2,benefitFaceValue:0,benefitUsageRate:0,purpose:"安定",status:"一軍"},
  {code:"1605",name:"INPEX",sector:"エネルギー",shares:1000,acquisitionPrice:1850,currentPrice:2250,annualDividendPerShare:86,benefitFaceValue:1000,benefitUsageRate:0.8,purpose:"配当",status:"二軍"},
  {code:"8593",name:"三菱HCキャピタル",sector:"金融・リース",shares:2500,acquisitionPrice:780,currentPrice:1080,annualDividendPerShare:40,benefitFaceValue:0,benefitUsageRate:0,purpose:"配当",status:"一軍"},
  {code:"7974",name:"任天堂",sector:"ゲーム",shares:300,acquisitionPrice:6200,currentPrice:8400,annualDividendPerShare:120,benefitFaceValue:10000,benefitUsageRate:0.5,purpose:"趣味",status:"優待枠"}
];
