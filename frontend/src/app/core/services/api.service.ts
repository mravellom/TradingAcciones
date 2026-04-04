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
  RiskProfile,
  HealthStatus,
} from '../../shared/models/trading.models';
import { environment } from '../../../environments/environment';

const BASE_URL = environment.apiUrl;

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
  getSignals(limit: number = 50, assetClass?: string): Observable<Signal[]> {
    const params: any = { limit };
    if (assetClass) params.asset_class = assetClass;
    return this.http.get<Signal[]>(`${BASE_URL}/signals`, { params });
  }

  getActiveSignals(): Observable<Signal[]> {
    return this.http.get<Signal[]>(`${BASE_URL}/signals/active`);
  }

  // Orders
  getOrders(limit: number = 50, assetClass?: string): Observable<Order[]> {
    const params: any = { limit };
    if (assetClass) params.asset_class = assetClass;
    return this.http.get<Order[]>(`${BASE_URL}/orders`, { params });
  }

  getActiveOrders(): Observable<Order[]> {
    return this.http.get<Order[]>(`${BASE_URL}/orders/active`);
  }

  // Positions
  getOpenPositions(): Observable<Position[]> {
    return this.http.get<Position[]>(`${BASE_URL}/positions/open`);
  }

  getPositions(limit: number = 50, assetClass?: string): Observable<Position[]> {
    const params: any = { limit };
    if (assetClass) params.asset_class = assetClass;
    return this.http.get<Position[]>(`${BASE_URL}/positions`, { params });
  }

  // Trades
  getTrades(limit: number = 50, assetClass?: string): Observable<Trade[]> {
    const params: any = { limit };
    if (assetClass) params.asset_class = assetClass;
    return this.http.get<Trade[]>(`${BASE_URL}/trades`, { params });
  }

  getWinRate(): Observable<{ win_rate: number }> {
    return this.http.get<{ win_rate: number }>(`${BASE_URL}/trades/win-rate`);
  }

  // Risk
  getRiskStatus(): Observable<RiskStatus> {
    return this.http.get<RiskStatus>(`${BASE_URL}/risk/status`);
  }

  getRiskProfile(): Observable<RiskProfile> {
    return this.http.get<RiskProfile>(`${BASE_URL}/risk/profile`);
  }

  switchRiskProfile(profileType: string): Observable<RiskProfile> {
    return this.http.post<RiskProfile>(`${BASE_URL}/risk/profile/switch`, {
      profile_type: profileType,
    });
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
