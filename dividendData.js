const DIVIDEND_EMPIRE_DEFAULT_SETTINGS={
  totalAssets:12800000,
  investedPrincipal:10200000,
  annualLivingCost:3600000,
  targetAssetAt60:200000000,
  milestones:[
    {age:45,amount:50000000},
    {age:50,amount:100000000},
    {age:55,amount:140000000},
    {age:60,amount:200000000}
  ],
  dividendLifestyleGoals:[
    {amount:100000,label:"家電・ガジェット予算"},
    {amount:300000,label:"年間の外食・温浴費"},
    {amount:500000,label:"国内旅行や趣味費"},
    {amount:1000000,label:"大型旅行や学習投資"},
    {amount:3000000,label:"生活費の大部分"},
    {amount:6000000,label:"配当生活ライン"}
  ]
};

const DIVIDEND_EMPIRE_DEFAULT_HOLDINGS=[
  {code:"SMP-001",name:"サンプル高配当食品",sector:"生活必需品",shares:400,acquisitionPrice:1800,currentPrice:2100,annualDividendPerShare:72,benefitFaceValue:3000,benefitUsageRate:0.7,purpose:"サンプル",status:"架空データ"},
  {code:"SMP-002",name:"サンプル通信インフラ",sector:"通信",shares:1200,acquisitionPrice:620,currentPrice:690,annualDividendPerShare:24,benefitFaceValue:0,benefitUsageRate:0,purpose:"サンプル",status:"架空データ"},
  {code:"SMP-003",name:"サンプル金融リース",sector:"金融",shares:800,acquisitionPrice:980,currentPrice:1150,annualDividendPerShare:42,benefitFaceValue:0,benefitUsageRate:0,purpose:"サンプル",status:"架空データ"},
  {code:"SMP-004",name:"サンプル医療機器",sector:"ヘルスケア",shares:250,acquisitionPrice:3600,currentPrice:3920,annualDividendPerShare:95,benefitFaceValue:5000,benefitUsageRate:0.5,purpose:"サンプル",status:"架空データ"},
  {code:"SMP-005",name:"サンプル物流REIT",sector:"不動産",shares:12,acquisitionPrice:145000,currentPrice:151000,annualDividendPerShare:5200,benefitFaceValue:0,benefitUsageRate:0,purpose:"サンプル",status:"架空データ"},
  {code:"SMP-006",name:"サンプル再エネ電力",sector:"公益",shares:600,acquisitionPrice:1320,currentPrice:1240,annualDividendPerShare:38,benefitFaceValue:2000,benefitUsageRate:0.8,purpose:"サンプル",status:"架空データ"}
];
