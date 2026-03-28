import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { ApiService } from './api.service';
import { environment } from '../../../environments/environment';

describe('ApiService', () => {
  let service: ApiService;
  let httpMock: HttpTestingController;
  const baseUrl = environment.apiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should get health status', () => {
    const mockHealth = { status: 'healthy', system_status: 'RUNNING', checks: {}, timestamp: '' };
    service.getHealth().subscribe((health) => {
      expect(health.status).toBe('healthy');
    });
    const req = httpMock.expectOne(`${baseUrl}/system/health`);
    expect(req.request.method).toBe('GET');
    req.flush(mockHealth);
  });

  it('should get portfolio', () => {
    const mockPortfolio = { total_balance: '10000', available_balance: '8000' };
    service.getPortfolio('PAPER').subscribe((p) => {
      expect(p.total_balance).toBe('10000');
    });
    const req = httpMock.expectOne((r) => r.url === `${baseUrl}/portfolio`);
    expect(req.request.params.get('mode')).toBe('PAPER');
    req.flush(mockPortfolio);
  });

  it('should get trades with limit', () => {
    service.getTrades(10).subscribe();
    const req = httpMock.expectOne((r) => r.url === `${baseUrl}/trades`);
    expect(req.request.params.get('limit')).toBe('10');
    req.flush([]);
  });

  it('should get open positions', () => {
    service.getOpenPositions().subscribe((p) => {
      expect(p).toEqual([]);
    });
    const req = httpMock.expectOne(`${baseUrl}/positions/open`);
    req.flush([]);
  });

  it('should get risk status', () => {
    service.getRiskStatus().subscribe();
    const req = httpMock.expectOne(`${baseUrl}/risk/status`);
    req.flush({});
  });

  it('should halt system', () => {
    service.haltSystem('test halt').subscribe();
    const req = httpMock.expectOne((r) => r.url === `${baseUrl}/system/halt`);
    expect(req.request.method).toBe('POST');
    req.flush({ status: 'HALTED' });
  });

  it('should approve order', () => {
    service.approveOrder('order-1').subscribe();
    const req = httpMock.expectOne(`${baseUrl}/orders/order-1/approve`);
    expect(req.request.method).toBe('POST');
    req.flush({});
  });

  it('should reject order with reason', () => {
    service.rejectOrder('order-1', 'too risky').subscribe();
    const req = httpMock.expectOne((r) => r.url === `${baseUrl}/orders/order-1/reject`);
    expect(req.request.params.get('reason')).toBe('too risky');
    req.flush({});
  });

  it('should get strategies', () => {
    service.getStrategies().subscribe((s) => {
      expect(s.length).toBe(0);
    });
    httpMock.expectOne(`${baseUrl}/strategies`).flush([]);
  });

  it('should get analytics summary', () => {
    service.getAnalyticsSummary().subscribe();
    httpMock.expectOne(`${baseUrl}/analytics/summary`).flush({});
  });
});
