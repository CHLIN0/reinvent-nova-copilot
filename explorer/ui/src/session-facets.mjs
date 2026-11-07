/** Display/filter taxonomy over public catalogue fields. Category assignment is
 * our deterministic projection, not the original RainFocus attribute schema.
 * Raw labels and their provenance stay available; unknown labels are retained.
 */
export const FACET_DEFINITIONS = Object.freeze([
 {id:'format',label:'活動形式',primary:true},
 {id:'topic',label:'主題',primary:true},
 {id:'service',label:'服務與工具',primary:true},
 {id:'level',label:'難度'},
 {id:'audience',label:'適合角色'},
 {id:'industry',label:'產業'},
 {id:'style',label:'學習方式'},
 {id:'logistics',label:'活動特徵與參加條件'},
 {id:'venue',label:'場館'},
 {id:'date',label:'日期與時間'},
 {id:'custom',label:'我的標籤'},
 {id:'other',label:'其他原始標籤'},
]);
const normalized=value=>String(value??'').normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g,' ');
const text=value=>typeof value==='string'?value:String(value?.label||value?.name||value?.value||value?.id||'');
const values=value=>Array.isArray(value)?value:value==null||value===''?[]:[value];
const dictionary=labels=>new Set(labels.map(normalized));
const formats=dictionary(['Bootcamp','Breakout session',"Builders' session",'Chalk talk','Code talk','Exam prep','Gamified learning','Lab','Lightning talk','Workshop','Keynote','Innovation talk','GameDay','Game Day','Jam','Hackathon','AI League','Football Cup']);
const audiences=dictionary(['Academic / Researcher','Advisor / Consultant','Business Executive','Cloud Security Specialist','Data Engineer','Data Scientist','DevOps Engineer','Developer / Engineer','Entrepreneur (Founder/Co-Founder)','IT Administrator','IT Executive','IT Professional / Technical Manager','Sales / Marketing','Solution / Systems Architect','Student','System Administrator','Tech Explorer','Venture Capitalist']);
const industries=dictionary(['Advertising & Marketing','Automotive','Education','Energy & Utilities','Financial Services','Government','Healthcare & Life Sciences','Manufacturing & Industrial','Media & Entertainment','Nonprofit','Retail & Consumer Goods','Software & Internet','Sports','Telecommunications','Travel & Hospitality']);
const styles=dictionary(['Discussion','Hands-on','Lecture-style','Self-paced']);
const logistics=dictionary(['AWS Partners','Community-led','Customer story','Laptop required','New launches','Repeat','Sponsored','Walk up only']);
const venues=dictionary(['Caesars Forum','Caesars Palace','MGM Grand','Venetian','Wynn/Encore']);
const services=dictionary([
 "Kiro",
 "EC2 Image Builder",
 "Elastic Load Balancing (ELB)",
 "OpenSearch",
 "Oracle Database@AWS",
 "Red Hat OpenShift Service on AWS (ROSA)",
 "AWS Amplify",
 "AWS AppConfig",
 "AWS AppSync",
 "AWS Application Discovery Service",
 "AWS Application Migration Service",
 "AWS Backup",
 "AWS Batch",
 "AWS Billing and Cost Management",
 "AWS Certificate Manager (ACM)",
 "AWS Cloud Development Kit (AWS CDK)",
 "AWS Cloud WAN",
 "AWS CloudFormation",
 "AWS CloudTrail",
 "AWS CodeBuild",
 "AWS CodeDeploy",
 "AWS CodePipeline",
 "AWS Command Line Interface (AWS CLI)",
 "AWS Compute Optimizer",
 "AWS Config",
 "AWS Context",
 "AWS Continuum",
 "AWS Control Tower",
 "AWS DataSync",
 "AWS Database Migration Service (AWS DMS)",
 "AWS Dedicated Local Zones",
 "AWS DevOps Agent",
 "AWS Device Farm",
 "AWS Direct Connect",
 "AWS Distro for OpenTelemetry",
 "AWS Elastic Beanstalk",
 "AWS Elastic Disaster Recovery",
 "AWS Elemental MediaConvert",
 "AWS Elemental MediaLive",
 "AWS Fargate",
 "AWS Fault Injection Service",
 "AWS Firewall Manager",
 "AWS Global Accelerator",
 "AWS Glue",
 "AWS GovCloud (US)",
 "AWS HealthLake",
 "AWS HealthOmics",
 "AWS IAM Access Analyzer",
 "AWS IAM Identity Center",
 "AWS Identity and Access Management (IAM)",
 "AWS Interconnect",
 "AWS IoT Core",
 "AWS IoT Greengrass",
 "AWS IoT SiteWise",
 "AWS Key Management Service (AWS KMS)",
 "AWS Lake Formation",
 "AWS Lambda",
 "AWS License Manager",
 "AWS Local Zones",
 "AWS Mainframe Modernization",
 "AWS Management Console",
 "AWS Marketplace",
 "AWS Network Firewall",
 "AWS Organizations",
 "AWS Outposts",
 "AWS Parallel Computing Service",
 "AWS Payment Cryptography",
 "AWS Private Certificate Authority",
 "AWS PrivateLink",
 "AWS RTB Fabric",
 "AWS Resilience Hub",
 "AWS Resource Explorer",
 "AWS Savings Plans",
 "AWS Secrets Manager",
 "AWS Security Agent",
 "AWS Security Hub",
 "AWS Security Incident Response",
 "AWS Security Token Service (AWS STS)",
 "AWS Service Catalog",
 "AWS Shield",
 "AWS Signer",
 "AWS Site-to-Site VPN",
 "AWS Step Functions",
 "AWS Systems Manager",
 "AWS Trainium",
 "AWS Transfer Family",
 "AWS Transform",
 "AWS Transit Gateway",
 "AWS WAF",
 "AWS Well-Architected Tool",
 "Amazon API Gateway",
 "Amazon Application Recovery Controller",
 "Amazon Athena",
 "Amazon Aurora",
 "Amazon Aurora DSQL",
 "Amazon Aurora for PostgreSQL",
 "Amazon Bedrock",
 "Amazon Braket",
 "Amazon CloudFront",
 "Amazon CloudWatch",
 "Amazon CloudWatch Application Insights",
 "Amazon CloudWatch Logs",
 "Amazon CodeGuru",
 "Amazon Cognito",
 "Amazon Connect",
 "Amazon Detective",
 "Amazon DevOps Guru",
 "Amazon DocumentDB (with MongoDB compatibility)",
 "Amazon DynamoDB",
 "Amazon DynamoDB Streams",
 "Amazon EC2 - Graviton",
 "Amazon EC2 Auto Scaling",
 "Amazon EC2 Linux",
 "Amazon EC2 Spot",
 "Amazon EMR",
 "Amazon ElastiCache",
 "Amazon ElastiCache Serverless",
 "Amazon Elastic Block Store (Amazon EBS)",
 "Amazon Elastic Compute Cloud (Amazon EC2)",
 "Amazon Elastic Container Registry (Amazon ECR)",
 "Amazon Elastic Container Service (Amazon ECS)",
 "Amazon Elastic File System (Amazon EFS)",
 "Amazon Elastic Kubernetes Service (Amazon EKS)",
 "Amazon Elastic Transcoder",
 "Amazon Elastic VMware Service (EVS)",
 "Amazon EventBridge",
 "Amazon FSx",
 "Amazon FSx for Lustre",
 "Amazon FSx for NetApp ONTAP",
 "Amazon FSx for OpenZFS",
 "Amazon FSx for Windows File Server",
 "Amazon GameLift",
 "Amazon GuardDuty",
 "Amazon Inspector",
 "Amazon Interactive Video Service (Amazon IVS)",
 "Amazon Kinesis",
 "Amazon Kinesis Data Streams",
 "Amazon Kinesis Video Streams",
 "Amazon Lex",
 "Amazon Lightsail",
 "Amazon MQ",
 "Amazon Managed Grafana",
 "Amazon Managed Service for Prometheus",
 "Amazon Managed Streaming for Apache Kafka (Amazon MSK)",
 "Amazon Managed Workflows for Apache Airflow (Amazon MWAA)",
 "Amazon Neptune",
 "Amazon Neptune Analytics",
 "Amazon Nova",
 "Amazon OpenSearch Serverless",
 "Amazon OpenSearch Service",
 "Amazon Q",
 "Amazon Q Business",
 "Amazon Q Developer",
 "Amazon Quick",
 "Amazon Quick Suite",
 "Amazon QuickSight",
 "Amazon Quicksight Q",
 "Amazon RDS for PostgreSQL",
 "Amazon Redshift",
 "Amazon Rekognition",
 "Amazon Relational Database Service (Amazon RDS)",
 "Amazon Route 53",
 "Amazon SageMaker",
 "Amazon SageMaker AI",
 "Amazon Simple Queue Service (Amazon SQS)",
 "Amazon Simple Storage Service (Amazon S3)",
 "Amazon Textract",
 "Amazon Transcribe",
 "Amazon VPC Lattice",
 "Amazon Verified Permissions",
 "Amazon Virtual Private Cloud (Amazon VPC)",
 "Amazon WorkSpaces",
 "Amazon WorkSpaces Core"
]);
const topics=dictionary(['Agentic AI','Analytics','Application Integration','Application Security','Architecture','Artificial Intelligence','Automation','Blockchain','Business Agents','Business Intelligence','Cloud Operations','Compute','Containers','Cost Optimization','Cryptography and Post-Quantum','Culture of Security','Customer Enablement','Data Protection','Databases','Developer Tools','DevOps','DevSecOps','Digital Sovereignty','Disaster Response & Recovery','Edge Computing','Event-Driven Architecture','Front-End Web & Mobile','Games','Generative AI','Global Infrastructure','Governance, Risk & Compliance','Hybrid Cloud & Multicloud','Identity & Access Management','Inclusion','Industry Solutions','Innovation & Transformation','Internet of Things','Kubernetes','Lambda-Based Applications','Learning from Amazon','Machine Learning','Management & Governance','Microsoft & .NET','Migration & Modernization','Monitoring & Observability','Network & Infrastructure Security','Networking & Content Delivery','Open Data','Open Source','Oracle','Privacy','Quantum Technologies','Resilience','Responsible AI','Robotics','SAP','SaaS','Security & Identity','Serverless','Storage','Sustainability','Tech for Impact','Threat Detection & Incident Response','Threat Intelligence','Training & Certification','VMware','Well-Architected Framework','Workforce Development','Zero Trust']);
const officialFieldCategories={Type:'format',Level:'level',Topic:'topic',SponsorSessionPrimaryTopic:'topic',AreaofInterest:'topic',Services:'service',Role:'audience',Industry:'industry',Venue:'venue',Walkuponlysession:'logistics',SessionAppendices:'logistics',Day:'date',DayTime:'date'};
// Preserve AWS Events' native dimensions instead of classifying prefixed copies
// as unrelated "other" tags. Unknown dimension semantics remain explicit.
const nativeFieldCategories={tracks:'topic',topics:'topic',industries:'industry',areasOfInterest:'topic',roles:'audience',services:'service',segments:'other',features:'other',customerPersonas:'audience',experiences:'other',additionalActivities:'logistics',focusAreas:'topic'};
function dateLabel(label){return /^(?:(?:\d{1,2}:\d{2})\s*(?:a\.?m\.?|p\.?m\.?)\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}$/i.test(label)||/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(label);}
function categoryFor(label){
 const n=normalized(label);
 if(formats.has(n))return 'format';
 if(/^(?:[1-5]00\s*[–—-]\s*(?:Foundational|Intermediate|Advanced|Expert|Distinguished)|No Level)$/i.test(label))return 'level';
 if(audiences.has(n))return 'audience';
 if(industries.has(n))return 'industry';
 if(styles.has(n))return 'style';
 if(logistics.has(n))return 'logistics';
 if(venues.has(n))return 'venue';
 if(dateLabel(label))return 'date';
 if(topics.has(n))return 'topic';
 if(services.has(n))return 'service';
 return 'other';
}
/** Every entry has a category key, raw-label provenance, and legacy aliases.
 * Inferred formats require an explicit title phrase; abstract mentions do not
 * turn a general session about games into a GameDay activity.
 */
export function sessionFacets(session={},taxonomy=[]){
 const entries=new Map(),topicLabels=new Map(values(taxonomy).map(t=>[t.id,t.label||t.id]));
 function add(label,category,source,field,alias,rawValue){
  label=text(label).trim();if(!label)return;
  const key=category+':'+normalized(label),provenance={source,field,value:rawValue??label};
  const entry=entries.get(key)||{key,label,category,source,aliases:[],provenance:[],sources:[],evidence:[]};
  if(alias&&!entry.aliases.includes(alias))entry.aliases.push(alias);
  if(!entry.sources.includes(source))entry.sources.push(source);
  if(!entry.provenance.some(p=>p.source===source&&p.field===field&&p.value===provenance.value))entry.provenance.push(provenance);
  if(!entry.evidence.includes(field))entry.evidence.push(field);
  // The primary source prefers an official field while preserving every source.
  if(source==='official')entry.source=source;
  entries.set(key,entry);
 }
 for(const [field,category] of Object.entries({type:'format',level:'level',venue:'venue',date_iso:'date',audience:'audience',learning_styles:'style',session_appendices:'logistics'}))
  for(const label of values(session[field]))add(label,category,'official',field);
 for(const [field,category] of Object.entries(nativeFieldCategories))
  for(const label of values(session[field])){
   const raw=text(label).trim();
   if(!raw)continue;
   add(category==='other'?field+': '+raw:raw,category,'official',field,'official:'+field+': '+raw,raw);
  }
 for(const tag of values(session.tags)){
  // The official adapter also keeps a flattened field-prefixed tag list. Its
  // identical native field above is authoritative; unrelated tags stay intact.
  const prefixed=text(tag).match(/^([^:]+):\s*(.+)$/);
  if(session.source==='aws_events_api'&&prefixed&&Object.hasOwn(nativeFieldCategories,prefixed[1])&&values(session[prefixed[1]]).some(value=>normalized(text(value))===normalized(prefixed[2])))continue;
  const label=text(tag);add(label,categoryFor(label),'official','tags','official:'+label);
 }
 // Also accepts explicit public attribute fields when an adapter exposes them.
 for(const attr of values(session.attributevalues)){
  if(!attr||typeof attr!=='object')continue;
  const label=text(attr.value),field=String(attr.attribute_id||attr.attribute||'');
  add(label,officialFieldCategories[field]||categoryFor(label),'official','attributevalues.'+field,'official:'+label);
 }
 for(const value of values(session.system_topics)){
  const id=typeof value==='string'?value:value?.id;if(!id)continue;
  add(topicLabels.get(id)||value?.label||id,'topic','system','system_topics','topic:'+id);
 }
 for(const value of values(session.custom_tags)){
  const label=text(value);add(label,'custom','custom','custom_tags','custom:'+label);
 }
 const title=String(session.title||'');
 for(const [label,pattern] of [['GameDay',/\bgame\s*day\b/i],['Jam',/\b(?:AWS\s+)?jam\b/i],['Hackathon',/\bhackathon\b/i],['AI League',/\bai\s+league\b/i],['Football Cup',/\bfootball\s+cup\b/i]])
  if(pattern.test(title))add(label,'format','inferred_title','title');
 if(session.status==='walk_up')add('Walk up only','logistics','official','status');
 const order=new Map(FACET_DEFINITIONS.map((f,i)=>[f.id,i]));
 return [...entries.values()].sort((a,b)=>order.get(a.category)-order.get(b.category)||a.label.localeCompare(b.label));
}
