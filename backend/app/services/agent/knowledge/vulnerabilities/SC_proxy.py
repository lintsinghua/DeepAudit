"""
智能合约代理漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

PROXY_UPGRADEABILITY = KnowledgeDocument(
    id="vuln_proxy_upgradeability",
    title="Proxy & Upgradeability Vulnerabilities",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["proxy", "upgrade", "initialization"],
    severity="critical",
    cwe_ids=["CWE-1188"],
    owasp_ids=["SC10:2026"],
    content="""

代理和可升级性漏洞描述了智能合约在使用可升级架构（如代理、信标或实现交换模式）时，其升级路径、初始化流程或管理员控制被错误设计或配置不当的情况。可升级合约将保存状态并委托调用的**代理（Proxy）**与包含实际业务逻辑的**实现（Implementation）**分离开来。
配置不当或治理薄弱的代理、初始化和升级机制，使得攻击者可以夺取实现的控制权或重新初始化关键状态。如果代理合约的初始化过程没有得到妥善处理，就可能成为致命的攻击入口。当可升级性未得到妥善保护时，攻击者可以劫持代理管理员或升级角色来部署恶意实现，或者绕过初始化和迁移步骤中的关键检查。

## 危险模式

### 未受保护的代理升级函数
```solidity
# 危险 - 没有任何访问控制，任何人都可以随意更改代理指向的逻辑实现
contract VulnerableProxyAdmin {
    address public admin;
    address public implementation;

    constructor(address _implementation) {
        admin = msg.sender;
        implementation = _implementation; //
    }

    function upgrade(address newImplementation) external {
        // Missing: access control (only admin) and sanity checks
        implementation = newImplementation; //
    }
}
```

### 未受保护的初始化逻辑 (Initialization Risks)
```solidity
# 危险 - 缺少 initializer 守卫，任何人都可以调用并成为 owner
contract VulnerableLogic {
    address public owner;

    // Missing initializer guard
    function initialize(address _owner) external {
        owner = _owner; //
    }
}
```

## 攻击方式与影响
1. 恶意升级： 攻击者利用未受保护的升级函数，将代理指向攻击者控制的恶意实现合约。
2. 重新初始化： 攻击者通过重新初始化来重置合约的所有权、配置或访问控制。
3. 存储冲突（Storage Collision）： 利用代理和实现之间的存储槽位重叠，导致关键数据被覆盖篡改。


## 检测要点
1. 审查升级和管理员角色（谁有权更改实现，以及存储布局的兼容性）。
2. 审查初始化和重新初始化逻辑（如未受保护的 initialize，缺失的 initializer 守卫）。
3. 审查代理委托机制（delegatecall 上下文中的 msg.sender / msg.value 传播问题）。
4. 审查存储布局（确保代理和实现之间不会发生槽位冲突，严格遵循仅追加（append-only）的存储规则）。

## 安全实践
1. 使用成熟的代理模式和库： 优先使用 OpenZeppelin 的 UUPS 或透明代理（Transparent Proxies），避免使用定制设计的升级机制。
2. 严格保护升级和管理员角色： 使用强大的治理机制或多重签名钱包来管理升级权限；绝不要在缺乏强力操作控制的情况下将其留给单一的 EOA（外部拥有账户）。
3. 应用初始化守卫： 正确使用 initializer 和 reinitializer 修饰符；并在逻辑合约部署后立即锁定它（Lock implementation contracts），防止被直接初始化。
4. 要求时间锁和多步操作： 对升级过程实施时间锁（Timelocks），提前公告升级提案，并在执行前留出审查和监控的时间。

## 修复示例
```solidity
# 安全 - 采用所有权访问控制、地址校验和事件日志的代理管理员合约
import "@openzeppelin/contracts/access/Ownable.sol"; //

contract SafeProxyAdmin is Ownable { //
    address public implementation; //

    event Upgraded(address indexed newImplementation); //
    error InvalidImplementation(); //

    constructor(address _implementation) {
        _setImplementation(_implementation); //
        _transferOwnership(msg.sender); //
    }

    function _setImplementation(address _implementation) internal {
        if (_implementation == address(0)) revert InvalidImplementation(); // 防范零地址配置
        implementation = _implementation; //
    }

    function upgrade(address newImplementation) external onlyOwner { // 严格的访问控制
        _setImplementation(newImplementation); //
        emit Upgraded(newImplementation); // 通过事件实现可观测性
    }
}
```

"""
)
