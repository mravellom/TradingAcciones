import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Portfolio,
  Signal,
  Order,
  Position,
  Trade,
  RiskStatus,
  HealthStatus,
} from '../../shared/models/trading.models';

const BASE_URL = 'http://localhost:8000/api/v1';

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  // System
  getHealth(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>(`${BASE_URL}/system/health`);
  }

  haltSystem(reason: string = 'Manual halt'): Observable<any> {
    return this.http.post(`${BASE_URL}/system/halt`, null, {
      params: { reason },
    });
  }

  resumeSystem(): Observable<any> {
    return this.http.post(`${BASE_URL}/system/resume`, null);
  }

  // Portfolio
  getPortfolio(mode: string = 'PAPER'): Observable<Portfolio> {
    return this.http.get<Portfolio>(`${BASE_URL}/portfolio`, {
      params: { mode },
    });
  }

  // Signals
  getSignals(limit: number = 50): Observable<Signal[]> {
    return this.http.get<Signal[]>(`${BASE_URL}/signals`, {
      params: { limit },
    });
  }

  getActiveSignals(): Observable<Signal[]> {
    return this.http.get<Signal[]>(`${BASE_URL}/signals/active`);
  }

  // Orders
  getOrders(limit: number = 50): Observable<Order[]> {
    return this.http.get<Order[]>(`${BASE_URL}/orders`, {
      params: { limit },
    });
  }

  getActiveOrders(): Observable<Order[]> {
    return this.http.get<Order[]>(`${BASE_URL}/orders/active`);
  }

  // Positions
  getOpenPositions(): Observable<Position[]> {
    return this.http.get<Position[]>(`${BASE_URL}/positions/open`);
  }

  getPositions(limit: number = 50): Observable<Position[]> {
    return this.http.get<Position[]>(`${BASE_URL}/positions`, {
      params: { limit },
    });
  }

  // Trades
  getTrades(limit: number = 50): Observable<Trade[]> {
    return this.http.get<Trade[]>(`${BASE_URL}/trades`, {
      params: { limit },
    });
  }

  getWinRate(): Observable<{ win_rate: number }> {
    return this.http.get<{ win_rate: number }>(`${BASE_URL}/trades/win-rate`);
  }

  // Risk
  getRiskStatus(): Observable<RiskStatus> {
    return this.http.get<RiskStatus>(`${BASE_URL}/risk/status`);
  }

  // Market
  getTicker(symbol: string): Observable<any> {
    return this.http.get(`${BASE_URL}/market/ticker/${symbol}`);
  }

  // Strategies
  getStrategies(): Observable<any[]> {
    return this.http.get<any[]>(`${BASE_URL}/strategies`);
  }

  createStrategy(data: any): Observable<any> {
    return this.http.post(`${BASE_URL}/strategies`, data);
  }

  updateStrategy(id: string, data: any): Observable<any> {
    return this.http.put(`${BASE_URL}/strategies/${id}`, data);
  }

  activateStrategy(id: string): Observable<any> {
    return this.http.post(`${BASE_URL}/strategies/${id}/activate`, null);
  }

  deactivateStrategy(id: string): Observable<any> {
    return this.http.post(`${BASE_URL}/strategies/${id}/deactivate`, null);
  }

  // Analytics
  getAnalyticsSummary(): Observable<any> {
    return this.http.get(`${BASE_URL}/analytics/summary`);
  }

  getCumulativePnl(days: number = 30): Observable<any[]> {
    return this.http.get<any[]>(`${BASE_URL}/analytics/pnl`, {
      params: { days },
    });
  }

  getDrawdown(days: number = 30): Observable<any[]> {
    return this.http.get<any[]>(`${BASE_URL}/analytics/drawdown`, {
      params: { days },
    });
  }

  getPerStrategyPerformance(): Observable<any[]> {
    return this.http.get<any[]>(`${BASE_URL}/analytics/per-strategy`);
  }

  getPaperVsLive(): Observable<any> {
    return this.http.get(`${BASE_URL}/analytics/paper-vs-live`);
  }

  // Approvals
  getPendingApprovals(): Observable<any[]> {
    return this.http.get<any[]>(`${BASE_URL}/orders/pending-approval`);
  }

  approveOrder(id: string): Observable<any> {
    return this.http.post(`${BASE_URL}/orders/${id}/approve`, null);
  }

  rejectOrder(id: string, reason: string = 'Manually rejected'): Observable<any> {
    return this.http.post(`${BASE_URL}/orders/${id}/reject`, null, {
      params: { reason },
    });
  }

  // ML Shadow
  getMLShadowPerformance(): Observable<any> {
    return this.http.get(`${BASE_URL}/analytics/ml-shadow`);
  }
}
