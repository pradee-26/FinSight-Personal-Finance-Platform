/**
 * FinSight Data Models and Types
 */

export interface User {
  id: string;
  username: string;
  email: string;
  passwordHash: string;
}

export interface Expense {
  id: string;
  userId: string;
  category: string;
  amount: number;
  date: string; // YYYY-MM-DD
  description: string;
  type: 'expense' | 'income';
}

export interface Budget {
  id: string;
  userId: string;
  category: string;
  amountLimit: number;
  period: 'monthly' | 'weekly';
}

export interface Investment {
  id: string;
  userId: string;
  symbol: string;
  name: string;
  quantity: number;
  buyPrice: number;
  currentPrice: number;
  assetType: 'stock' | 'crypto' | 'etf' | 'mutual_fund' | 'bond';
  lastUpdated: string;
}

export interface FinancialGoal {
  id: string;
  userId: string;
  name: string;
  targetAmount: number;
  currentAmount: number;
  deadline: string; // YYYY-MM-DD
  category: string;
}

export interface IntelligentAlert {
  id: string;
  userId: string;
  type: 'warning' | 'info' | 'recommendation' | 'success';
  message: string;
  date: string; // ISO date
  read: boolean;
}

export interface AIDispatchRequest {
  expenses: Expense[];
  budgets: Budget[];
  investments: Investment[];
  goals: FinancialGoal[];
  customPrompt?: string;
}

export interface AIDispatchResponse {
  insights: string[];
  recommendations: Array<{
    title: string;
    description: string;
    impact: 'high' | 'medium' | 'low';
    category: 'budgeting' | 'investment' | 'saving' | 'debt';
  }>;
  marketAlerts: string[];
}
