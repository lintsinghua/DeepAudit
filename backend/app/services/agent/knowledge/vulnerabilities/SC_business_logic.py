"""
智能合约业务逻辑漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

LOGIC_ERRORS = KnowledgeDocument(
    id="vuln_logic_errors",
    title="Logic Errors",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["logic", "business"],
    severity="high",
    cwe_ids=["CWE-840"],
    owasp_ids=["SC03:2025"],
    content="""
逻辑错误（也称为业务逻辑漏洞）是智能合约中隐蔽的缺陷，发生在合约代码未能匹配其预期行为时。当合约的行为偏离其预期功能时，就会发生这些漏洞。这些错误通常隐藏在合约的逻辑中，表现形式包括奖励分配中的数学计算错误、不当的代币铸造机制，或借贷逻辑中的错误计算。

## 危险模式

### 借贷池不平衡与不当的代币铸造
逻辑错误常表现为借贷池不平衡（对存款和取款的跟踪不正确导致池储备不一致）或不当的代币铸造（未经检查或错误的铸造逻辑允许无限或意外的代币生成）。
```solidity
# 危险 - 错误的计算和未经验证的铸造逻辑
contract Solidity_LogicErrors {
    mapping(address => uint256) public userBalances;
    uint256 public totalLendingPool;

    function deposit() public payable {
        userBalances[msg.sender] += msg.value; //
        totalLendingPool += msg.value; //
    }

    function withdraw(uint256 amount) public {
        require(userBalances[msg.sender] >= amount, "Insufficient balance"); //

        // Faulty calculation: Incorrectly reducing the user's balance without updating the total lending pool
        userBalances[msg.sender] -= amount; //

        // This should update the total lending pool, but it's omitted here.

        payable(msg.sender).transfer(amount); //
    }

    function mintReward(address to, uint256 rewardAmount) public {
        // Faulty minting logic: Reward amount not validated
        userBalances[to] += rewardAmount; //
    }
}
```

## 攻击方式
1. 攻击者利用不正确的奖励分配或池不平衡来抽干合约资金。
2. 攻击者利用未经检查或错误的铸造逻辑进行过度代币铸造，从而增加代币供应量，破坏协议信任和价值。
3. 这些漏洞可能导致智能合约行为异常甚至完全无法使用，造成运营失败并给用户和利益相关者带来重大的财务损失。
4. 现实中遭受业务逻辑攻击的智能合约案例包括 Level Finance Hack 和 BNO Hack。

## 检测要点
1. 审查奖励分配逻辑中是否存在导致在利益相关者之间分配不公的计算错误。
2. 检查代币铸造机制是否存在允许无限或意外生成代币的未校验逻辑。
3. 检查借贷池逻辑中对存款和取款的跟踪是否正确，以防由于状态变量（如总池子余额）遗漏更新而导致池储备不一致。

## 安全实践
1. 编写涵盖所有可能的业务逻辑场景的全面测试用例来验证代码。
2. 进行彻底的代码审查和审计，以识别和修复潜在的逻辑错误。
3. 记录每个函数和模块的预期行为，并将其与实际实现进行比较以确保一致性。
4. 实施护栏措施，例如使用安全数学库防止计算错误、对代币铸造实施适当的制衡措施，以及采用可审计的奖励分配算法。

## 修复示例
```solidity
# 安全 - 正确更新所有相关状态变量并验证输入参数
contract Solidity_LogicErrors {
    mapping(address => uint256) public userBalances;
    uint256 public totalLendingPool;

    function deposit() public payable {
        userBalances[msg.sender] += msg.value; //
        totalLendingPool += msg.value; //
    }

    function withdraw(uint256 amount) public {
        require(userBalances[msg.sender] >= amount, "Insufficient balance"); //

        // Correctly reducing the user's balance and updating the total lending pool
        userBalances[msg.sender] -= amount; //
        totalLendingPool -= amount; //

        payable(msg.sender).transfer(amount); //
    }

    function mintReward(address to, uint256 rewardAmount) public {
        require(rewardAmount > 0, "Reward amount must be positive"); //

        // Safeguarded minting logic
        userBalances[to] += rewardAmount; //
    }
}
```


""",
)

FLASH_LOAN = KnowledgeDocument(
    id="vuln_flash_loan",
    title="Flash Loan Attacks",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["flash-loan", "defi", "manipulation"],
    severity="critical",
    cwe_ids=["CWE-840"],
    owasp_ids=["SC07:2025"],
    content="""
闪贷攻击（Flash Loan Attacks）是指攻击者利用无抵押的、在同一笔交易中借贷的资金（即闪电贷）来将底层漏洞放大为有利可图的、耗尽协议资金的攻击。闪电贷本身作为一种 DeFi 原语并没有漏洞，但它们在一个交易内为攻击者提供了任意巨大的瞬时资金。虽然闪电贷很有用，但它可以被利用在单笔交易中执行多个操作来操纵协议。


任何基于“处于风险中的资金”或“历史头寸规模”进行信任假设的协议都可能受到威胁，因为攻击者可以暂时持有巨额余额而无需承担自身资金风险。闪电贷通常作为一种“力量倍增器（force multiplier）”，将业务逻辑、预言机、算术或访问控制等小缺陷转变成灾难性的漏洞利用。

## 危险模式

### 缺乏速率限制且包含微小舍入偏差的逻辑
```solidity
# 危险 - 容易受到闪电贷循环攻击的简单份额铸造逻辑
contract VulnerablePool {
    // ... 状态变量 ...
    function deposit(uint256 assets) external {
        uint256 shares;
        if (totalShares == 0) {
            shares = assets; //
        } else {
            shares = (assets * totalShares) / totalAssets; //
        }

        totalAssets += assets; //
        totalShares += shares; //
        sharesOf[msg.sender] += shares; //
    }
    // 没有任何防止闪电贷推动的存款/取款循环的保护措施
}
# 上述代码在舍入时总是向下截断；但在没有任何最大滑点、限制或操作频率考虑的情况下，经过反复的闪电贷推动的循环，微调的公式或错误计算的状态可能会变成攻击者的净收益。
```

###攻击方式
攻击者通常构造批处理交易执行以下步骤：
1. 通过闪电贷（如 Aave、dYdX、Uniswap V3）借入巨额资本。
2. 利用借来的资金操纵协议状态、价格或记账。
3. 提取利润（例如抽干流动性、获取抵押不足的贷款、扭曲治理）。
4. 在同一笔交易中偿还闪电贷并保留利润。
这通常会导致流动性枯竭、价格被更改或业务逻辑被利用。现实案例包括 2025 年的 Bunni（损失 840 万美元）和 zkLend（损失 950 万美元），在这两起事件中，闪电贷都放大了基础的舍入错误，使得微小的精度增益变成了巨额损失。

###检测要点
1. 检查治理和投票逻辑（是否存在利用闪电贷买票或操纵快照的风险）。
2. 检查预言机和定价机制（是否能用借来的流动性操纵 DEX 或时间加权平均价格）。
3. 检查份额和记账逻辑（在假设输入有界的情况下的舍入或比例计算）。
4. 检查清算和抵押品检查（依赖于头寸规模的阈值）。
5. 检查可组合性假设（是否在单笔交易中绝对信任调用者的余额或池状态）。

###安全实践
1. 假设闪电贷存在： 在设计经济和记账逻辑时，要假设攻击者可以获得任意规模的、瞬时的资金。
2. 对敏感操作进行限流： 对高影响的状态转换实施每区块或每纪元（epoch）的限制，或使用随着操作规模/频率增加的动态费用。
3. 限制单次交互的敞口： 设置最大滑点、最大头寸规模和借款上限，限制单笔交易中可以改变的状态量。
4. 模拟闪电贷场景： 在 QA 和审计中包含闪电贷风格的测试，并使用模糊测试来发现有利可图的多重调用序列。
5. 结合强大的预言机和逻辑： 闪电贷通常只是放大器，必须从根本上修复底层的算术、业务逻辑或预言机问题。

## 修复示例
```solidity
# 安全 - 引入基本的速率限制和明确的舍入策略
contract SaferPool {
    // ... 状态变量 ...
    uint256 public lastUpdateBlock; //
    error TooFrequentInteraction(); //

    modifier rateLimited() {
        // 简单示例：限制高影响操作每区块仅一次
        if (lastUpdateBlock == block.number) revert TooFrequentInteraction(); //
        _;
        lastUpdateBlock = block.number; //
    }

    function deposit(uint256 assets) external rateLimited { //
        require(assets > 0, "zero assets"); //

        uint256 shares;
        if (totalShares == 0) {
            shares = assets; //
        } else {
            // 使用有利于协议且经过正式分析的明确舍入策略
            shares = (assets * totalShares + totalAssets - 1) / totalAssets; //
        }

        totalAssets += assets; //
        totalShares += shares; //
        sharesOf[msg.sender] += shares; //
    }
}
```



"""
)

GAS_LIMIT = KnowledgeDocument(
    id="vuln_gas_limit",
    title="Gas Limit Vulnerabilities",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["gas", "loop", "array"],
    severity="medium",
    cwe_ids=["CWE-400"],
    owasp_ids=["SC09:2023"],
    content="""
在以太坊等区块链平台上，智能合约执行的每个操作都会消耗一定量的 Gas，而区块 Gas 限制（Block Gas Limit）规定了单个区块中可以使用的最大 Gas 量。如果智能合约中的某个函数完成执行所需的 Gas 超过了区块 Gas 限制，该交易将会失败。这种漏洞在遍历动态数据结构（如数组或列表）的循环中尤为常见，因为其迭代次数不固定且可能变得任意大，极易因资源耗尽而面临交易失败的风险。


## 危险模式

### 依赖动态变量的无限制循环
当循环的迭代次数由用户控制或与可能无限增长的动态数组挂钩时，非常容易超出区块的 Gas 上限。

```solidity
# 危险 - 循环次数由用户传入的 _amount 控制，效率低下且可能耗尽 Gas
contract TokenTransfer {
    mapping(address => uint256) public balances;

    function transfer(address _to, uint256 _amount) public {
        require(balances[msg.sender] >= _amount, "Insufficient balance"); //
        
        // The loop iterates _amount times, which can be very inefficient and can potentially exceed the block gas limit if _amount is too large.
        for (uint256 i = 0; i < _amount; i++) {  
            balances[msg.sender]--; //
            balances[_to]++; //
        }
    }
}
```

## 攻击方式与影响
1. 容易受到 Gas 限制问题影响的函数可能会变得无法执行。
2. 当这些函数因超出 Gas 限制而无法完成时，会导致合约状态冻结。
3. 任何与该失败交易相关的资金都将保持不可访问状态，从而有效地将它们锁定在合约内。

## 检测要点
1. 检查合约中是否存在 for 或 while 循环，并审查它们是否用于遍历动态数据结构（如数组、列表）。
2. 确认控制循环迭代次数的变量是否受外部输入控制，或者是否可能随着合约生命周期无限制地增长。
3. 检查循环体内部执行的操作复杂度，因为每次迭代的微小 Gas 增加都会在长循环中被显著放大。

##安全实践
1. 函数必须验证用户无法控制循环内部用于遍历大量数据的变量长度。
2. 如果代码逻辑上无法省略遍历操作，则应根据业务逻辑对迭代长度设置明确的限制（最大上限）。
3. 在 Solidity 中使用循环时，开发者应特别注意循环内部发生的操作，确保交易不会消耗过多 Gas，且永远不会超过区块的 Gas 限制。

## 修复示例
```solidity
# 安全 - 避免使用不必要的循环，直接通过算术运算修改状态，使 Gas 消耗保持在恒定值 (O(1))
contract TokenTransferFixed {
    mapping(address => uint256) public balances;

    function transfer(address _to, uint256 _amount) public {
        require(balances[msg.sender] >= _amount, "Insufficient balance");
        
        // 直接执行状态更新，无论金额多大，Gas 成本都是固定的
        balances[msg.sender] -= _amount; 
        balances[_to] += _amount; 
    }
}
```

"""
)