"""
智能合约外部漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

UNCHECKED_EXTERNAL_CALLS = KnowledgeDocument(
    id="vuln_unchecked_external_calls",
    title="Unchecked External Calls",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["external-call", "unchecked"],
    severity="high",
    cwe_ids=["CWE-252"],
    owasp_ids=["SC06:2025"],
    content="""
未检查的外部调用是指智能合约在调用另一个合约或地址时（通过 `call`、`delegatecall`、`staticcall` 或高级调用如 `transfer`/`send`），未能完全考虑被调用者的行为、返回值或重入潜力的任何情况。未能验证外部函数调用的成功可能导致意料之外的后果。当被调用的合约失败时，调用合约可能会错误地继续执行，从而危及完整性和功能。

调用合约隐式信任被调用者会按预期运行——返回成功、不重入并且不执行任意逻辑。当这种假设被打破时，调用者可能会陷入不一致的状态或被利用。这类漏洞通常不是单一的根本原因，而是促成重入攻击、业务逻辑漏洞和记账不一致的关键因素。


## 危险模式

### 忽略返回值并在外部调用后更新状态
```solidity
# 危险 - 忽略外部调用的返回值，并在调用后才更新状态
contract VulnerablePayout {
    // ... 状态变量 ...

    function claim() external {
        uint256 amount = rewards[msg.sender];
        require(amount > 0, "no rewards");

        // Vulnerable: does not check return value or reentrancy
        token.transfer(msg.sender, amount); //

        // State update after external call
        rewards[msg.sender] = 0; //
    }
}
#上述代码忽略了 transfer 的返回值；如果转移失败，用户的奖励余额并未清零，但用户也没有收到代币（静默失败）。同时，状态更新发生在外部调用之后，为恶意代币留下了重入的机会。
```

## 攻击方式与影响
1. 重入攻击： 攻击者通过在回调函数或与转移挂钩的代币中实现恶意逻辑来进行重入利用。
2. 静默失败： 当忽略返回值（如遇到非标准的 ERC-20 代币）时，合约会留下不一致的状态。
3. 意外代码执行： 当调用由用户提供或协议可配置的地址时，可能执行非预期的任意代码。

## 检测要点
1. 检查代币转移（ERC-20、ERC-721、ERC-1155）以及代码中对非标准返回值或回滚行为的处理。
2. 检查回调和钩子接口（例如 ERC-777 tokensReceived、ERC-4626 钩子、onFlashLoan）。
3. 检查底层调用（call、delegatecall、callcode）及其对 Gas 和存储的影响。
4. 检查重入可能跨越多个合约的可组合性流程。

## 安全实践
1. 将所有外部调用视为不可信： 即使是“标准”代币或知名协议也可能被升级或替换，应当假设它们可能会意外地重入或回滚。
2. 使用检查-生效-交互（Checks-Effects-Interactions）模式： 验证前提条件，然后更新内部状态，最后才执行外部调用。
3. 在支付时优先使用“拉取（pull）”而非“推送（push）”： 允许用户主动提取资金，而不是在循环中将资金推送到任意地址。
4. 检查返回值并处理失败模式： 使用如 OpenZeppelin 的 SafeERC20 库来包装代币操作。
5. 对底层调用和任意回调保持极度谨慎。

## 修复示例
'''solidity
# 安全 - 先更新状态，并严格检查外部调用的返回值
contract SafePayout {
    // ... 状态变量 ...

    function claim() external {
        uint256 amount = rewards[msg.sender];
        if (amount == 0) revert NoRewards(); //

        // Move state change *before* external call to mitigate reentrancy on this variable
        rewards[msg.sender] = 0; //

        bool ok = token.transfer(msg.sender, amount); //
        if (!ok) {
            // revert and restore state if needed
            revert TransferFailed(); //
        }
    }
}
'''

""",
)


PRICE_ORACLE_MANIPULATION = KnowledgeDocument(
    id="vuln_price_oracle_manipulation",
    title="Price Oracle Manipulation",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["oracle", "price", "manipulation"],
    severity="critical",
    cwe_ids=["CWE-252"],
    owasp_ids=["SC02:2025"],
    content="""
价格预言机操纵漏洞发生在智能合约依赖于可被攻击者直接或间接影响的价格或估值数据时，导致协议基于错误的值做出决策。预言机代表着信任边界：合约隐式地信任其接收到的价格反映了真实的或链上的市场状况。当这种信任因操纵、数据陈旧或配置错误而被破坏时，协议行为就会被扭曲。
这会影响所有消耗价格数据的合约类型：DeFi 借贷（抵押估值、清算）、AMM 和 DEX（现货和基于 TWAP 的定价）、收益金库（净值计算、份额估值）、流动性质押和衍生品、NFT 和代币估值，以及跨链桥（用于铸造/销毁比率的资产定价）。


## 危险模式

### 单一来源且缺乏完整性校验的喂价
```solidity
# 危险 - 单点预言机且缺乏对数据新鲜度和边界的校验
interface IPriceFeed {
    function getLatestPrice() external view returns (int);
}

contract PriceOracleManipulation {
    address public owner;
    IPriceFeed public priceFeed;

    constructor(address _priceFeed) {
        owner = msg.sender;
        priceFeed = IPriceFeed(_priceFeed);
    }

    function borrow(uint256 amount) public {
        int price = priceFeed.getLatestPrice();
        require(price > 0, "Price must be positive");

        // Vulnerability: No validation or protection against price manipulation
        uint256 collateralValue = uint256(price) * amount;

        // Borrow logic based on manipulated price
        // If an attacker manipulates the oracle, they could borrow more than they should
    }

    function repay(uint256 amount) public {
        // Repayment logic
    }
}
#上述代码仅依赖单一的预言机源，没有聚合或合理性检查；缺乏对历史值的上限/下限或偏差检查；并且经济参数（100% LTV）使得即使是微小的操纵也有利可图。
```
## 攻击方式
1. 攻击者通过同一区块内的大额交易、闪电贷或 JIT（即时）流动性来操纵现货价格。
2. 在极短的时间窗口或低流动性期间操纵 TWAP（时间加权平均价格）。
3. 当合约未强制检查数据新鲜度或缺乏后备机制时，利用陈旧或卡死的数据。

## 检测要点
1. 审查基于 DEX 的预言机（现货价格、TWAP、几何平均数）及其对闪电贷、JIT 流动性或集中流动性倾斜的抵抗力。
2. 审查链下和混合数据源（Chainlink、Pyth、自定义中继器）中关于新鲜度、偏差和多源聚合的逻辑假设。
3. 审查底层价格源的流动性和市场深度（薄弱池与深层市场对比）。
4. 审查跨链和 L2 定价模型（最终性延迟、排序器顺序、消息中继假设）。

## 安全实践
1. 聚合多个数据源： 使用几个 DEX 或预言机的中位数/平均值，拒绝异常值和反常的偏差。
2. 基于时间的防御： 在足够长的窗口内使用 TWAP 以抵御短命的操纵，并拒绝超过最大陈旧时间阈值的过时价格。
3. 流动性感知设计： 避免将核心价格基于缺乏流动性的池子，并限制单个池子/数据源对全局定价的影响。
4. 故障安全行为： 在数据可疑或不可用时，暂停敏感操作（如借贷、清算）；在参数更改上使用熔断机制和速率限制。

修复示例
```solidity
# 安全 - 采用带完整性元数据校验的预言机聚合器
contract RobustOracleLending {
    // ... 状态变量与常量 ...

    function _getSafePrice() internal view returns (uint256) {
        (
            , // roundId
            int256 answer, //
            , // startedAt
            uint256 updatedAt, //
            uint80 answeredInRound //
        ) = priceFeed.latestRoundData(); //
        
        require(answer > 0, "bad answer"); //
        require(updatedAt != 0 && block.timestamp - updatedAt <= MAX_DELAY, "stale price"); //
        require(answeredInRound != 0, "incomplete round"); //
        
        return uint256(answer); //
    }

    // ... 采用更保守的抵押率 (如 75%) 的借贷逻辑 ...
}
```

"""
)

LACK_OF_INPUT_VALIDATION = KnowledgeDocument(
    id="vuln_lack_of_input_validation",
    title="Lack of Input Validation",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["input", "validation"],
    severity="high",
    cwe_ids=["CWE-20"],
    owasp_ids=["SC04:2025"],
    content="""
缺少输入验证描述了智能合约处理外部数据（如函数参数、调用数据、跨链消息或签名有效负载）时，未严格强制要求数据格式正确、在预期范围内以及已授权进行预期操作的情况。不充分的输入验证可能导致漏洞，攻击者可能通过提供有害或意外的输入来操纵合约，从而潜在地破坏逻辑或导致意外行为。假设输入是良性的合约，会使自身容易受到格式错误或对抗性数据的影响，这些数据会将系统推向不安全的状态、破坏记账或绕过预期的检查。


## 危险模式

### 脆弱的参数处理与配置
当合约接受管理员或用户的配置输入但缺少边界检查时，会导致关键参数被设置为破坏协议的危险值。
```solidity
# 危险 - 缺少访问控制和边界检查
contract LackOfInputValidation {
    mapping(address => uint256) public balances;
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Caller is not authorized");
        _;
    }

    function setBalance(address user, uint256 amount) public onlyOwner {
        require(user != address(0), "Invalid address");
        balances[user] = amount;
    }
}

## 攻击方式
1. 攻击者利用破坏不变量的越界值（例如，费用 > 100%、零金额、最大 uint 值）。
2. 攻击者提供绕过允许列表或导致意外行为的格式错误的地址或有效负载。
3. 当合约未验证 nonce、过期时间或链 ID 时，执行重放和排序攻击。


## 检测要点
1. 审查数值参数（如金额、费用、利率、滑点、抵押率）及其安全边界。
2. 审查地址变量（如零地址检查、合约与 EOA 的假设、委托或代理地址）。
3. 审查链下和签名数据的校验逻辑（签名有效性、过期时间、防重放 nonce）。
4. 审查跨链和桥接有效负载（消息格式、链 ID、发送者验证）。
5. 审查管理员和治理输入（配置值、升级参数），这些输入经常被隐式信任，但错误配置同样具有破坏性。

## 安全实践
1. 验证所有外部输入，包括函数参数、链下签名数据和跨链消息有效负载。
2. 强制执行严格的不变量，例如明确费用、利率、杠杆和抵押率的范围，以及对关键地址设置非零要求。
3. 使用自定义错误和显式检查，以保持验证逻辑清晰且节省 Gas。
4. 在被验证之前，将管理员和治理输入同样视为不受信任的数据——错误配置的破坏力与显式漏洞利用一样大。
5. 对无效输入实施负面测试（模糊测试、属性测试），以确保系统确实能拒绝意外值。

修复示例
```solidity
# 安全 - 具有严格边界验证、访问控制和自定义错误的配置逻辑
contract LackOfInputValidation {
    mapping(address => uint256) public balances;
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Caller is not authorized");
        _;
    }

    function setBalance(address user, uint256 amount) public onlyOwner {
        require(user != address(0), "Invalid address");
        balances[user] = amount;
    }
}
```
"""
)