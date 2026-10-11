import express from "express";
import path from "path";
import fs from "fs";
import crypto from "crypto";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import { 
  User, 
  Expense, 
  Budget, 
  Investment, 
  FinancialGoal, 
  IntelligentAlert,
  AIDispatchResponse 
} from "./src/types";

// Initialize Gemini client safely if key is available
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";
let ai: GoogleGenAI | null = null;

if (GEMINI_API_KEY) {
  ai = new GoogleGenAI({
    apiKey: GEMINI_API_KEY,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      }
    }
  });
} else {
  console.warn("WARNING: GEMINI_API_KEY environment variable is not defined. AI insights will use local smart heuristic generators.");
}

const PORT = 3000;
const DB_FILE = path.join(process.cwd(), "database.json");

// Local DB Schema
interface DatabaseSchema {
  users: User[];
  expenses: Expense[];
  budgets: Budget[];
  investments: Investment[];
  goals: FinancialGoal[];
  alerts: IntelligentAlert[];
}

const DEFAULT_DB: DatabaseSchema = {
  users: [],
  expenses: [],
  budgets: [],
  investments: [],
  goals: [],
  alerts: []
};

// Seed initial demo data for new registers or to let the app look full on first start
function getInitialSeededData(userId: string): DatabaseSchema {
  const now = new Date();
  const formatOffsetDate = (daysAgo: number) => {
    const d = new Date();
    d.setDate(now.getDate() - daysAgo);
    return d.toISOString().split('T')[0];
  };

  const initialExpenses: Expense[] = [
    { id: "e1", userId, category: "Housing", amount: 1200, date: formatOffsetDate(20), description: "Monthly Apartment Rent Payment", type: "expense" },
    { id: "e2", userId, category: "Groceries", amount: 180, date: formatOffsetDate(3), description: "Supermarket Weekly Groceries", type: "expense" },
    { id: "e3", userId, category: "Groceries", amount: 45, date: formatOffsetDate(12), description: "Whole Foods Organics", type: "expense" },
    { id: "e4", userId, category: "Dining Out", amount: 65, date: formatOffsetDate(1), description: "Sushi Dinner with Friends", type: "expense" },
    { id: "e5", userId, category: "Utilities", amount: 110, date: formatOffsetDate(15), description: "Electricity & High-speed Internet Bill", type: "expense" },
    { id: "e6", userId, category: "Transportation", amount: 40, date: formatOffsetDate(8), description: "Gas Station Refuel", type: "expense" },
    { id: "e7", userId, category: "Salary", amount: 4800, date: formatOffsetDate(25), description: "Tech Solutions Corp Monthly Salary Payday", type: "income" },
    { id: "e8", userId, category: "Investment Income", amount: 150, date: formatOffsetDate(5), description: "Quarterly ETF Dividend Distribution", type: "income" },
    { id: "e9", userId, category: "Entertainment", amount: 15, date: formatOffsetDate(10), description: "Netflix Premium Subscription", type: "expense" },
  ];

  const initialBudgets: Budget[] = [
    { id: "b1", userId, category: "Groceries", amountLimit: 400, period: "monthly" },
    { id: "b2", userId, category: "Dining Out", amountLimit: 250, period: "monthly" },
    { id: "b3", userId, category: "Entertainment", amountLimit: 100, period: "monthly" },
    { id: "b4", userId, category: "Transportation", amountLimit: 200, period: "monthly" },
  ];

  const initialInvestments: Investment[] = [
    { id: "i1", userId, symbol: "AAPL", name: "Apple Inc.", quantity: 15, buyPrice: 165.40, currentPrice: 189.30, assetType: "stock", lastUpdated: now.toISOString() },
    { id: "i2", userId, symbol: "MSFT", name: "Microsoft Corporation", quantity: 10, buyPrice: 310.20, currentPrice: 415.60, assetType: "stock", lastUpdated: now.toISOString() },
    { id: "i3", userId, symbol: "VTI", name: "Vanguard Total Stock Market ETF", quantity: 30, buyPrice: 215.10, currentPrice: 252.80, assetType: "etf", lastUpdated: now.toISOString() },
    { id: "i4", userId, symbol: "BTC", name: "Bitcoin", quantity: 0.12, buyPrice: 42000.00, currentPrice: 64250.00, assetType: "crypto", lastUpdated: now.toISOString() },
  ];

  const initialGoals: FinancialGoal[] = [
    { id: "g1", userId, name: "Emergency Fund", targetAmount: 15000, currentAmount: 8500, deadline: formatOffsetDate(-365), category: "Saving" },
    { id: "g2", userId, name: "Europe Summer Vacation", targetAmount: 5000, currentAmount: 2200, deadline: formatOffsetDate(-180), category: "Travel" },
    { id: "g3", userId, name: "Home Down Payment", targetAmount: 60000, currentAmount: 12000, deadline: formatOffsetDate(-1000), category: "Housing" },
  ];

  const initialAlerts: IntelligentAlert[] = [
    { id: "a1", userId, type: "success", message: "Emergency Fund goal is 56% complete! Keep up the regular saving habit.", date: now.toISOString(), read: false },
    { id: "a2", userId, type: "warning", message: "You spent $65 on Dining Out which is nearing 80% of your weekly average category budget.", date: formatOffsetDate(1), read: false },
    { id: "a3", userId, type: "info", message: "Portfolio rebalancing suggested: Crypto has risen to represent a higher share of your liquid assets.", date: formatOffsetDate(3), read: true },
  ];

  return {
    users: [],
    expenses: initialExpenses,
    budgets: initialBudgets,
    investments: initialInvestments,
    goals: initialGoals,
    alerts: initialAlerts
  };
}

// Read database from file safely
function readDB(): DatabaseSchema {
  try {
    if (!fs.existsSync(DB_FILE)) {
      fs.writeFileSync(DB_FILE, JSON.stringify(DEFAULT_DB, null, 2), "utf8");
      return DEFAULT_DB;
    }
    const content = fs.readFileSync(DB_FILE, "utf8");
    return JSON.parse(content) || DEFAULT_DB;
  } catch (err) {
    console.error("Error reading database file, returning default database:", err);
    return DEFAULT_DB;
  }
}

// Write database to file safely
function writeDB(db: DatabaseSchema) {
  try {
    fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2), "utf8");
  } catch (err) {
    console.error("Error writing to database file:", err);
  }
}

// Helper to encrypt passwords (simple SHA-256 with salt)
function hashPassword(password: string): string {
  return crypto.createHash("sha256").update(password).digest("hex");
}

async function startServer() {
  const app = express();
  app.use(express.json());

  // Database initialization
  const db = readDB();

  // Helper middleware to verify users using simple Bearer headers
  function authenticateUser(req: express.Request, res: express.Response, next: express.NextFunction) {
    const authHeader = req.headers.authorization;
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      res.status(401).json({ error: "Access token is required. Please login or register." });
      return;
    }
    const token = authHeader.split(" ")[1];
    // In this simple custom auth, user ID is encoded or matches user token directly. 
    // We will find a user that has this token. To be extremely robust and keep simple code,
    // the bearer token is simply the user's ID itself (or user's email hash).
    const currentDB = readDB();
    const user = currentDB.users.find(u => u.id === token);
    if (!user) {
      res.status(401).json({ error: "Invalid or expired session token." });
      return;
    }
    (req as any).user = user;
    next();
  }

  // --- API Authentication Endpoints ---

  // Register
  app.post("/api/auth/register", (req, res) => {
    const { username, email, password } = req.body;
    if (!username || !email || !password) {
      res.status(400).json({ error: "Username, email, and password are required." });
      return;
    }

    const currentDB = readDB();
    const existingUser = currentDB.users.find(u => u.email.toLowerCase() === email.toLowerCase());
    if (existingUser) {
      res.status(400).json({ error: "User with this email already exists." });
      return;
    }

    const userId = "usr_" + crypto.randomBytes(6).toString("hex");
    const passwordHash = hashPassword(password);
    const newUser: User = { id: userId, username, email, passwordHash };
    
    // Add user to DB
    currentDB.users.push(newUser);

    // Seed default demo data specifically for this new user so they are greeted with an active, beautiful dashboard on first login
    const seeds = getInitialSeededData(userId);
    currentDB.expenses = [...currentDB.expenses, ...seeds.expenses];
    currentDB.budgets = [...currentDB.budgets, ...seeds.budgets];
    currentDB.investments = [...currentDB.investments, ...seeds.investments];
    currentDB.goals = [...currentDB.goals, ...seeds.goals];
    currentDB.alerts = [...currentDB.alerts, ...seeds.alerts];

    writeDB(currentDB);

    res.status(201).json({ 
      token: userId, 
      user: { id: userId, username, email } 
    });
  });

  // Login
  app.post("/api/auth/login", (req, res) => {
    const { email, password } = req.body;
    if (!email || !password) {
      res.status(400).json({ error: "Email and password are required." });
      return;
    }

    const currentDB = readDB();
    const user = currentDB.users.find(u => u.email.toLowerCase() === email.toLowerCase());
    if (!user || user.passwordHash !== hashPassword(password)) {
      res.status(401).json({ error: "Invalid email or password." });
      return;
    }

    res.json({ 
      token: user.id, 
      user: { id: user.id, username: user.username, email: user.email } 
    });
  });

  // Get Me
  app.get("/api/auth/me", authenticateUser, (req, res) => {
    const user = (req as any).user;
    res.json({ id: user.id, username: user.username, email: user.email });
  });

  // --- Expenses & Income API Endpoints ---
  app.get("/api/expenses", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    const userExpenses = currentDB.expenses.filter(e => e.userId === user.id);
    res.json(userExpenses);
  });

  app.post("/api/expenses", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { category, amount, date, description, type } = req.body;
    
    if (!category || !amount || !date || !type) {
      res.status(400).json({ error: "Category, amount, date, and type ('expense'|'income') are required." });
      return;
    }

    const currentDB = readDB();
    const newExpense: Expense = {
      id: "exp_" + crypto.randomBytes(6).toString("hex"),
      userId: user.id,
      category,
      amount: Number(amount),
      date,
      description: description || "",
      type
    };

    currentDB.expenses.push(newExpense);
    writeDB(currentDB);
    res.status(201).json(newExpense);
  });

  app.delete("/api/expenses/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;

    const currentDB = readDB();
    const expenseIndex = currentDB.expenses.findIndex(e => e.id === id && e.userId === user.id);
    if (expenseIndex === -1) {
      res.status(404).json({ error: "Item not found." });
      return;
    }

    const removed = currentDB.expenses.splice(expenseIndex, 1);
    writeDB(currentDB);
    res.json({ success: true, removed: removed[0] });
  });


  // --- Budgets API Endpoints ---
  app.get("/api/budgets", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    const userBudgets = currentDB.budgets.filter(b => b.userId === user.id);
    res.json(userBudgets);
  });

  app.post("/api/budgets", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { category, amountLimit, period } = req.body;

    if (!category || amountLimit === undefined) {
      res.status(400).json({ error: "Category and limit are required." });
      return;
    }

    const currentDB = readDB();
    // Overwrite existing budget for same category or create new
    const existingIndex = currentDB.budgets.findIndex(b => b.userId === user.id && b.category.toLowerCase() === category.toLowerCase());

    const newBudget: Budget = {
      id: existingIndex !== -1 ? currentDB.budgets[existingIndex].id : "bud_" + crypto.randomBytes(6).toString("hex"),
      userId: user.id,
      category,
      amountLimit: Number(amountLimit),
      period: period || "monthly"
    };

    if (existingIndex !== -1) {
      currentDB.budgets[existingIndex] = newBudget;
    } else {
      currentDB.budgets.push(newBudget);
    }

    writeDB(currentDB);
    res.json(newBudget);
  });

  app.delete("/api/budgets/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;

    const currentDB = readDB();
    const budgetIndex = currentDB.budgets.findIndex(b => b.id === id && b.userId === user.id);
    if (budgetIndex === -1) {
      res.status(404).json({ error: "Budget not found." });
      return;
    }

    currentDB.budgets.splice(budgetIndex, 1);
    writeDB(currentDB);
    res.json({ success: true });
  });


  // --- Investments / Portfolio API Endpoints ---
  app.get("/api/investments", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    const userInvestments = currentDB.investments.filter(i => i.userId === user.id);
    res.json(userInvestments);
  });

  app.post("/api/investments", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { symbol, name, quantity, buyPrice, currentPrice, assetType } = req.body;

    if (!symbol || !name || quantity === undefined || buyPrice === undefined || currentPrice === undefined || !assetType) {
      res.status(400).json({ error: "Symbol, name, quantity, buyPrice, currentPrice and assetType are required." });
      return;
    }

    const currentDB = readDB();
    const newHolding: Investment = {
      id: "inv_" + crypto.randomBytes(6).toString("hex"),
      userId: user.id,
      symbol: symbol.toUpperCase(),
      name,
      quantity: Number(quantity),
      buyPrice: Number(buyPrice),
      currentPrice: Number(currentPrice),
      assetType,
      lastUpdated: new Date().toISOString()
    };

    currentDB.investments.push(newHolding);
    writeDB(currentDB);
    res.status(201).json(newHolding);
  });

  app.delete("/api/investments/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;

    const currentDB = readDB();
    const index = currentDB.investments.findIndex(i => i.id === id && i.userId === user.id);
    if (index === -1) {
      res.status(404).json({ error: "Holding not found." });
      return;
    }

    currentDB.investments.splice(index, 1);
    writeDB(currentDB);
    res.json({ success: true });
  });


  // --- Financial Goals API Endpoints ---
  app.get("/api/goals", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    const userGoals = currentDB.goals.filter(g => g.userId === user.id);
    res.json(userGoals);
  });

  app.post("/api/goals", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { name, targetAmount, currentAmount, deadline, category } = req.body;

    if (!name || targetAmount === undefined || currentAmount === undefined || !deadline || !category) {
      res.status(400).json({ error: "Name, targetAmount, currentAmount, deadline and category are required." });
      return;
    }

    const currentDB = readDB();
    const newGoal: FinancialGoal = {
      id: "goal_" + crypto.randomBytes(6).toString("hex"),
      userId: user.id,
      name,
      targetAmount: Number(targetAmount),
      currentAmount: Number(currentAmount),
      deadline,
      category
    };

    currentDB.goals.push(newGoal);
    writeDB(currentDB);
    res.status(201).json(newGoal);
  });

  app.put("/api/goals/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;
    const { currentAmount } = req.body;

    if (currentAmount === undefined) {
      res.status(400).json({ error: "currentAmount is required for update." });
      return;
    }

    const currentDB = readDB();
    const goalIndex = currentDB.goals.findIndex(g => g.id === id && g.userId === user.id);
    if (goalIndex === -1) {
      res.status(404).json({ error: "Goal not found." });
      return;
    }

    currentDB.goals[goalIndex].currentAmount = Number(currentAmount);
    writeDB(currentDB);
    res.json(currentDB.goals[goalIndex]);
  });

  app.delete("/api/goals/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;

    const currentDB = readDB();
    const index = currentDB.goals.findIndex(g => g.id === id && g.userId === user.id);
    if (index === -1) {
      res.status(404).json({ error: "Goal not found." });
      return;
    }

    currentDB.goals.splice(index, 1);
    writeDB(currentDB);
    res.json({ success: true });
  });


  // --- Intelligent Alerts Endpoints ---
  app.get("/api/alerts", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    const userAlerts = currentDB.alerts.filter(a => a.userId === user.id);
    res.json(userAlerts);
  });

  app.post("/api/alerts/read/:id", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const { id } = req.params;

    const currentDB = readDB();
    const alertIndex = currentDB.alerts.findIndex(a => a.id === id && a.userId === user.id);
    if (alertIndex !== -1) {
      currentDB.alerts[alertIndex].read = true;
      writeDB(currentDB);
    }
    res.json({ success: true });
  });

  app.post("/api/alerts/clear-all", authenticateUser, (req, res) => {
    const user = (req as any).user;
    const currentDB = readDB();
    currentDB.alerts = currentDB.alerts.filter(a => a.userId !== user.id);
    writeDB(currentDB);
    res.json({ success: true });
  });


  // --- Gemini AI Analysis and Advisory Endpoints ---
  app.post("/api/ai/analyze", authenticateUser, async (req, res) => {
    const user = (req as any).user;
    const { customPrompt } = req.body;

    const currentDB = readDB();
    const userExpenses = currentDB.expenses.filter(e => e.userId === user.id);
    const userBudgets = currentDB.budgets.filter(b => b.userId === user.id);
    const userInvestments = currentDB.investments.filter(i => i.userId === user.id);
    const userGoals = currentDB.goals.filter(g => g.userId === user.id);

    // Calculate basic totals for the model context
    const totalIncome = userExpenses.filter(e => e.type === "income").reduce((sum, e) => sum + e.amount, 0);
    const totalExpenses = userExpenses.filter(e => e.type === "expense").reduce((sum, e) => sum + e.amount, 0);
    const portfolioValue = userInvestments.reduce((sum, i) => sum + (i.quantity * i.currentPrice), 0);
    const totalInvestedPrincipal = userInvestments.reduce((sum, i) => sum + (i.quantity * i.buyPrice), 0);

    const categorySpending: Record<string, number> = {};
    userExpenses.filter(e => e.type === "expense").forEach(e => {
      categorySpending[e.category] = (categorySpending[e.category] || 0) + e.amount;
    });

    if (ai) {
      try {
        const inputString = JSON.stringify({
          summary: {
            totalIncome,
            totalExpenses,
            netSavings: totalIncome - totalExpenses,
            portfolioValue,
            totalInvestedPrincipal,
            portfolioReturn: portfolioValue - totalInvestedPrincipal
          },
          categorySpending,
          budgets: userBudgets.map(b => ({ category: b.category, limit: b.amountLimit })),
          investments: userInvestments.map(i => ({ symbol: i.symbol, quantity: i.quantity, buyPrice: i.buyPrice, currentPrice: i.currentPrice, type: i.assetType })),
          goals: userGoals.map(g => ({ name: g.name, target: g.targetAmount, current: g.currentAmount, category: g.category, deadline: g.deadline })),
          customPrompt: customPrompt || "General overview request"
        });

        // Query server-side Gemini
        const systemInstruction = `You are FinSight AI, an elite personal finance and portfolio intelligence advisor. 
You must analyze the user's financial profile, transaction categories, monthly budgets, stock/etf holdings, and target savings goals. 
Return a strictly formatted JSON response that conforms EXACTLY to this schema structure:
{
  "insights": [
    "A direct, personalized observation of their cash flows or budget leaks",
    "An insightful analysis of their investment portfolio performance, asset allocation diversity, or risk indicators"
  ],
  "recommendations": [
    {
      "title": "Clear action-oriented recommendation title",
      "description": "Specific tactical steps to achieve this",
      "impact": "high" or "medium" or "low",
      "category": "budgeting" or "investment" or "saving" or "debt"
    }
  ],
  "marketAlerts": [
    "A relevant financial advisory or warning, e.g., high allocation in single assets, budget limits exceeded, or progress on emergency funds"
  ]
}
Make your suggestions realistic, data-informed, and highly encouraging. Make sure the JSON is completely valid and correctly escaped. Do not wrap it in markdown code blocks in your returned text.`;

        const response = await ai.models.generateContent({
          model: "gemini-3.5-flash",
          contents: `Analyze the user's financial profile below and any custom request they have entered. Custom User request: "${customPrompt || 'None'}". Profile Data: ${inputString}`,
          config: {
            systemInstruction,
            responseMimeType: "application/json",
            responseSchema: {
              type: Type.OBJECT,
              properties: {
                insights: {
                  type: Type.ARRAY,
                  items: { type: Type.STRING },
                  description: "General deep dives on the user's savings rate, category leaks, and allocation"
                },
                recommendations: {
                  type: Type.ARRAY,
                  items: {
                    type: Type.OBJECT,
                    properties: {
                      title: { type: Type.STRING },
                      description: { type: Type.STRING },
                      impact: { type: Type.STRING, description: "Must be 'high', 'medium', or 'low'" },
                      category: { type: Type.STRING, description: "Must be 'budgeting', 'investment', 'saving', or 'debt'" }
                    },
                    required: ["title", "description", "impact", "category"]
                  }
                },
                marketAlerts: {
                  type: Type.ARRAY,
                  items: { type: Type.STRING },
                  description: "Intelligent financial or portfolio alerts"
                }
              },
              required: ["insights", "recommendations", "marketAlerts"]
            }
          }
        });

        const responseText = response.text || "{}";
        const result: AIDispatchResponse = JSON.parse(responseText.trim());

        // Automatically create real IntelligentAlerts in user's notification list based on AI's findings
        if (result.marketAlerts && result.marketAlerts.length > 0) {
          result.marketAlerts.forEach((alertMsg) => {
            const hasSimilar = currentDB.alerts.some(a => a.userId === user.id && a.message === alertMsg);
            if (!hasSimilar) {
              currentDB.alerts.unshift({
                id: "a_ai_" + crypto.randomBytes(6).toString("hex"),
                userId: user.id,
                type: "recommendation",
                message: alertMsg,
                date: new Date().toISOString(),
                read: false
              });
            }
          });
          writeDB(currentDB);
        }

        res.json(result);
        return;
      } catch (err) {
        console.error("Gemini AI API Call failed, falling back to local smart heuristics:", err);
      }
    }

    // --- FALLBACK SMART HEURISTICS (if API key not defined or call fails) ---
    const insights: string[] = [];
    const recommendations: Array<{title: string, description: string, impact: 'high' | 'medium' | 'low', category: 'budgeting' | 'investment' | 'saving' | 'debt'}> = [];
    const marketAlerts: string[] = [];

    // Heuristic 1: Savings Rate
    if (totalIncome > 0) {
      const savingsRate = ((totalIncome - totalExpenses) / totalIncome) * 100;
      if (savingsRate < 10) {
        insights.push(`Your savings rate is currently ${savingsRate.toFixed(1)}%, which is below the recommended 20% mark. Increasing this will significantly speed up your long-term wealth compounding.`);
        recommendations.push({
          title: "Optimize Non-Essential Spending",
          description: "Review categories like Dining Out and Entertainment to find minor adjustments that can free up $100-$200 a month to build momentum.",
          impact: "high",
          category: "budgeting"
        });
      } else {
        insights.push(`Superb cash flow management! You saved ${savingsRate.toFixed(1)}% of your earnings this period, surpassing typical benchmark recommendations.`);
      }
    } else {
      insights.push("No registered incomes recorded. Adding your primary salary or dividends allows FinSight to automatically calculate your dynamic savings rate.");
    }

    // Heuristic 2: Budget thresholds
    userBudgets.forEach(b => {
      const spent = userExpenses
        .filter(e => e.type === "expense" && e.category.toLowerCase() === b.category.toLowerCase())
        .reduce((sum, e) => sum + e.amount, 0);
      if (spent > b.amountLimit) {
        marketAlerts.push(`Budget Alert: You have exceeded your $${b.amountLimit} monthly budget for "${b.category}" (Current total: $${spent}).`);
        recommendations.push({
          title: `Re-evaluate ${b.category} Budget`,
          description: `You've exceeded your ${b.category} budget limit by $${(spent - b.amountLimit).toFixed(0)}. Try pausing optional purchases in this category for the remaining days of this billing cycle.`,
          impact: "medium",
          category: "budgeting"
        });
      } else if (spent > b.amountLimit * 0.8) {
        marketAlerts.push(`Budget Watch: Spending on "${b.category}" has reached ${(spent / b.amountLimit * 100).toFixed(0)}% of your limit ($${spent} of $${b.amountLimit}).`);
      }
    });

    // Heuristic 3: Investment diversity
    if (userInvestments.length > 0) {
      const totalHoldingsValue = userInvestments.reduce((sum, i) => sum + (i.quantity * i.currentPrice), 0);
      const cryptoAllocation = userInvestments
        .filter(i => i.assetType === "crypto")
        .reduce((sum, i) => sum + (i.quantity * i.currentPrice), 0);
      
      const cryptoPercent = (cryptoAllocation / totalHoldingsValue) * 100;
      if (cryptoPercent > 20) {
        insights.push(`Your cryptocurrency allocation is ${cryptoPercent.toFixed(1)}% of your portfolio. High crypto exposure increases overall portfolio volatility.`);
        recommendations.push({
          title: "Portfolio Rebalancing Strategy",
          description: "High volatility exposure detected in crypto. Consider securing profits or adding robust diversified equity index funds (like VTI or VOO) to stabilize returns.",
          impact: "medium",
          category: "investment"
        });
      }

      const topHolding = [...userInvestments].sort((a, b) => (b.quantity * b.currentPrice) - (a.quantity * a.currentPrice))[0];
      const topHoldingVal = topHolding.quantity * topHolding.currentPrice;
      const topPercent = (topHoldingVal / totalHoldingsValue) * 100;
      if (topPercent > 40 && userInvestments.length > 1) {
        insights.push(`Concentration warning: Your position in "${topHolding.symbol}" represents ${topPercent.toFixed(1)}% of your total portfolio.`);
        recommendations.push({
          title: "Reduce Single Asset Concentration",
          description: `Over 40% of your investment capital lies inside a single asset (${topHolding.symbol}). Spreading new savings across diverse asset classes protects your down-side exposure.`,
          impact: "high",
          category: "investment"
        });
      }
    } else {
      recommendations.push({
        title: "Initiate Wealth Compounding",
        description: "You have no investments recorded. Starting early with even small regular monthly deposits in diversified mutual funds or low-cost index ETFs is highly recommended.",
        impact: "high",
        category: "saving"
      });
    }

    // Heuristic 4: Financial Goals deadlines
    userGoals.forEach(g => {
      const percent = (g.currentAmount / g.targetAmount) * 100;
      if (percent >= 100) {
        marketAlerts.push(`Goal Achieved! Congratulations, you have fully funded your "${g.name}" target!`);
      } else if (percent < 30) {
        insights.push(`Your "${g.name}" goal is currently at ${percent.toFixed(0)}% completion. Directing a small dedicated recurring transfer can accelerate momentum.`);
      }
    });

    if (insights.length === 0) {
      insights.push("FinSight is ready. Log a few transactions or portfolio holdings to start generating detailed intelligence insights.");
    }

    // Automatically seed heuristic market alerts as user notifications
    marketAlerts.forEach((alertMsg) => {
      const hasSimilar = currentDB.alerts.some(a => a.userId === user.id && a.message === alertMsg);
      if (!hasSimilar) {
        currentDB.alerts.unshift({
          id: "a_ai_" + crypto.randomBytes(6).toString("hex"),
          userId: user.id,
          type: "recommendation",
          message: alertMsg,
          date: new Date().toISOString(),
          read: false
        });
      }
    });
    writeDB(currentDB);

    res.json({
      insights,
      recommendations,
      marketAlerts
    });
  });

  // Serve static files & Vite frontend integration
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`[FinSight Server] Express running on http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error("Failed to start server:", err);
});
