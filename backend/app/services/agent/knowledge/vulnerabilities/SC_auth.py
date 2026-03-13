"""
智能合约权限漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

ACCESS_CONTROL = KnowledgeDocument(
    id="vuln_access_control",
    title="Access Control Vulnerabilities",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["access-control", "authorization"],
    severity="critical",
    cwe_ids=["CWE-284", "CWE-285"],
    owasp_ids=["SC01:2025"],
    content="""
不当的访问控制描述了智能合约未严格执行*谁*可以调用特权行为、*在什么条件*下以及使用*哪些参数*的任何情况。在现代 DeFi 系统中，这远不止一个单一的 `onlyOwner` 修饰符，还涉及治理合约、多重签名、监护人、代理管理员和跨链路由器等。如果信任边界薄弱或应用不一致，攻击者可能会冒充特权角色或使系统将不受信任的地址视为已授权。当与其他问题（如逻辑缺陷或可升级性漏洞）结合时，访问控制失效可能导致整个协议被破坏。


## 危险模式

###敏感函数缺失修饰符或角色检查
```solidity
# 危险 - 任何人都可以转移所有权并提取资金
contract LiquidityPoolVulnerable {
    address public owner;
    mapping(address => uint256) public balances;

    // Anyone can set a new owner – critical access control bug
    function transferOwnership(address newOwner) external {
        owner = newOwner; // No access control
    }

    // Intended to be called only by the owner to rescue tokens
    function emergencyWithdraw(address to, uint256 amount) external {
        // Missing: require(msg.sender == owner)
        require(balances[address(this)] >= amount, "insufficient"); //
        balances[address(this)] -= amount; //
        balances[to] += amount; //
    }
}
```

###回调入口点缺失调用者验证
在许多 DeFi 协议（如 Uniswap V4 的 Hook 或闪电贷回调）中，如果回调函数没有限制仅允许受信任的地址（如 PoolManager）调用，攻击者可以直接调用这些回调来欺骗协议。

## 攻击方式
1. 攻击者直接调用缺少修饰符或角色检查的敏感函数（例如直接铸造代币或提取储备金）。
2. 利用对 msg.sender 的错误假设（例如，通过委托调用或元交易）或跨模块的权限混淆。
3. 攻击未受保护的代理初始化或重新初始化逻辑。

## 检测要点
1. 检查所有权/管理员控制逻辑（例如 onlyOwner，治理、多重签名地址配置）是否在敏感函数中强制执行。
2. 检查升级和暂停机制（代理管理员、监护人）的权限配置。
3. 检查资金移动和记账逻辑（如铸造/销毁代币、池子重构、费用路由）是否受到保护。
4. 检查跨链或跨模块边界（跨链桥、金库路由器、L2 信使）的信任验证逻辑。
5. 检查所有钩子（Hook）和回调入口点是否在链上明确验证了调用者身份。

## 安全实践
1. 使用经过实战检验的原语（如 OpenZeppelin 的 Ownable 和 AccessControl）而不是定制的角色系统。
2. 特权角色应该精简、有明确的文档记录，并最好由高度安全的多重签名或治理模块持有，而不是由单点故障的外部拥有账户 (EOA) 控制。
3. 对代理和核心组件的升级路径应严格控制并具有可观测性，对每次权限更改或升级发出事件，以便链下监控可以快速检测到滥用。
4. 任何跨链或跨模块的“所有者”概念必须在链上进行验证，而不是假设来自消息源。
5. 避免对地址进行隐式信任（例如避免“部署者永远受信任”的假设），并使用具有明确职责分离的基于角色的访问控制 (RBAC)。

##修复示例
```solidity
# 安全 - 使用基于角色的访问控制 (RBAC) 严格限制权限
import "@openzeppelin/contracts/access/AccessControl.sol";

contract LiquidityPoolSecure is AccessControl {
    bytes32 public constant GOVERNANCE_ROLE = keccak256("GOVERNANCE_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    mapping(address => uint256) public balances;

    event EmergencyWithdraw(address indexed to, uint256 amount, address indexed triggeredBy);

    constructor(address governance, address guardian) {
        _grantRole(DEFAULT_ADMIN_ROLE, governance);
        _grantRole(GOVERNANCE_ROLE, governance);
        _grantRole(GUARDIAN_ROLE, guardian);
    }

    function grantGovernance(address newGov) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _grantRole(GOVERNANCE_ROLE, newGov);
    }

    function setGuardian(address newGuardian) external onlyRole(GOVERNANCE_ROLE) {
        _grantRole(GUARDIAN_ROLE, newGuardian);
    }

    // Only governance or designated guardians can trigger emergency withdrawals
    function emergencyWithdraw(address to, uint256 amount)
        external
        onlyRole(GUARDIAN_ROLE)
    {
        require(to != address(0), "invalid to");
        require(balances[address(this)] >= amount, "insufficient");
        balances[address(this)] -= amount;
        balances[to] += amount;

        emit EmergencyWithdraw(to, amount, msg.sender);
    }
}
```

"""
)



