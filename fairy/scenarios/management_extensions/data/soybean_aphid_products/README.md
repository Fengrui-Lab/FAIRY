# 大豆蚜虫产品资料与模拟假设

这里服务于单田大豆选药场景，不包含新作物品种或独立评分体系。

## 真实商品及资料

- **Transform WG / Corteva，sulfoxaflor，IRAC 4C**。厂商大豆资料给出0.75–1.0 oz产品/acre；最小重复间隔14天，采收间隔7天，单季最多4次、最多8.5 oz/acre，连续最多2次。产品用质量g记录。[厂商产品页](https://www.corteva.com/us/products-and-solutions/crop-protection/transform-wg.html)、[大豆资料PDF](https://www.corteva.com/content/dam/dpagco/corteva/na/us/en/products/files/TransformWG_Soybean_FS.pdf)。
- **Sefina Inscalis / BASF，afidopyropen，IRAC 9D**。厂商大豆资料给出3 fl oz产品/acre，最小间隔7天、采收间隔7天、季节总量6 fl oz/acre；按此剂量最多2次。产品用体积mL记录。[厂商产品页](https://agriculture.basf.us/crop-protection/products/insecticides/sefina.html)、[大豆资料PDF](https://agriculture.basf.us/content/dam/cxm/agriculture/crop-protection/products/documents/sefina/BASF_TechBulletin_Sefina_Soybean_2019_medres.pdf)。

两份2019厂商资料保存在本目录，SHA256写入`catalog.json`并在新场景初始化时核验。产品页于2026-11-03查询；冻结资料是明确的美国参考资料，不声称中国登记或完整复刻任一地区全部监管规则。

换算使用1acre=4046.8564224m²；干重1oz=28.349523125g；美制1fl oz=29.5735295625mL。g和mL不能互换，商品制剂和配药水不能互换。

## 明确的模拟条件

- 供应报价固定为Transform0.16DEMO/g、Sefina0.12DEMO/mL。按允许的最低剂量折算，每公顷产品费用约8.41和26.31DEMO；这是声明的经营输入，**不是采集到的市场价格或现实性价比排名**。
- 承包地面喷施费7.5DEMO/ha，服务自带配药水和燃料，供水100L/ha、耗时120分钟/ha。每次最多4垄，同垄七天内只提供一次单产品服务，不提供混配。这些是模拟服务合同条件，单独于药品说明事实。
- 两种药在允许剂量内都接入现有FAIRY经验模型：压力初降65%、持效10天、期间抑制压力增长55%，受现有天气洗脱规则影响。未建立两种真实药品各自的田间药效、抗药性或天敌模型；相同模型效果不代表真实效果相同。
- 生长期一次性虫害迁入通过现有`PressureEvent`产生；处理改变压力，再通过现有WOFOST外部生物胁迫接口影响PGASS和后续生长。没有直接改收获公斤数。
- 现有模型对较低压力仍有连续生长惩罚，因此模型里的经济最优重复次数不能当作真实田间用药次数。250蚜虫/株等参考来自[明尼苏达大学推广资料](https://extension.umn.edu/agriculture/crop-production/soybean/insecticide-options-for-resistant-soybean-aphid)；场景只给“蚜虫等效”诊断，既非实测虫数，也没有真实植株受害比例，不能机械套用田间阈值。

## 数据与业务边界

官方WUR `Soybean_901`参数保持不变。气象为既有Thionville2019逐日驱动，属于跨地区参考模拟，未作本地田间标定。商品身份/资料、模拟报价/服务和经验药效在`catalog.json`分别标明。

药品购买、商品制剂库存、实际消耗费用、未用库存资产、服务费用分别记账。工具检查剂量、间隔、次数和轮换；新场景的拖拉机适配还检查实际施药后的采收间隔。所有状态可JSON保存，恢复时校验目录身份和物料/现金守恒。
