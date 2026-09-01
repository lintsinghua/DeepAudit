"""
XXE (XML外部实体注入) 漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


XXE = KnowledgeDocument(
    id="vuln_xxe",
    title="XML External Entity (XXE) Injection",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["xxe", "xml", "entity", "injection", "ssrf"],
    severity="high",
    cwe_ids=["CWE-611"],
    owasp_ids=["A05:2021"],
    content="""
XXE允许攻击者通过XML外部实体读取服务器文件、执行SSRF攻击或导致拒绝服务。

## 危险模式

### Python
```python
# 危险 - lxml默认配置
from lxml import etree
doc = etree.parse(user_xml)
doc = etree.fromstring(user_xml)

# 危险 - xml.etree (Python < 3.7.1)
import xml.etree.ElementTree as ET
ET.parse(user_xml)

# 危险 - xml.dom
from xml.dom import minidom
minidom.parseString(user_xml)
```

### Java
```java
// 危险 - DocumentBuilder默认配置
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
DocumentBuilder db = dbf.newDocumentBuilder();
Document doc = db.parse(userInput);

// 危险 - SAXParser
SAXParserFactory spf = SAXParserFactory.newInstance();
SAXParser parser = spf.newSAXParser();
parser.parse(userInput, handler);
```

### PHP
```php
// 危险
$doc = simplexml_load_string($xml);
$doc = new DOMDocument();
$doc->loadXML($xml);
```

## 攻击载荷

### 文件读取
```xml
<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<root>&xxe;</root>
```

### SSRF
```xml
<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "http://internal-server/api">
]>
<root>&xxe;</root>
```

### 拒绝服务 (Billion Laughs)
```xml
<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<root>&lol3;</root>
```

## 检测要点
1. 所有XML解析代码
2. 是否禁用了外部实体
3. 是否禁用了DTD处理
4. 用户输入是否直接解析

## 安全实践
1. 禁用外部实体
2. 禁用DTD处理
3. 使用JSON代替XML
4. 输入验证

## 修复示例

### Python
```python
# 安全 - lxml禁用实体
from lxml import etree
parser = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    dtd_validation=False,
    load_dtd=False
)
doc = etree.parse(user_xml, parser)

# 安全 - defusedxml
import defusedxml.ElementTree as ET
doc = ET.parse(user_xml)
```

### Java
```java
// 安全 - 禁用外部实体
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
dbf.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
dbf.setFeature("http://xml.org/sax/features/external-general-entities", false);
dbf.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
```

### PHP
```php
// 安全 - 禁用外部实体 (PHP >= 5.4)
$old = libxml_disable_entity_loader(true);
$doc = simplexml_load_string($xml);
libxml_disable_entity_loader($old);

// 安全 - DOMDocument 禁用网络与外部实体
$doc = new DOMDocument();
$doc->loadXML($xml, LIBXML_NONET | LIBXML_NOENT | LIBXML_DTDLOAD);

// 安全 - SimpleXML 配合 LIBXML_NONET
$doc = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
```
""",
)
