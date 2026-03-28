import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { DashboardComponent } from './dashboard.component';

describe('DashboardComponent', () => {
  let component: DashboardComponent;
  let fixture: ComponentFixture<DashboardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(DashboardComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with no portfolio', () => {
    expect(component.portfolio).toBeNull();
  });

  it('should start with empty positions', () => {
    expect(component.openPositions).toEqual([]);
  });

  it('should format USD correctly', () => {
    expect(component.formatUsd('1234.5')).toBe('1,234.50');
  });

  it('should return correct PnL class', () => {
    expect(component.getPnlClass('100')).toBe('positive');
    expect(component.getPnlClass('-50')).toBe('negative');
    expect(component.getPnlClass('0')).toBe('neutral');
  });

  it('should format percent correctly', () => {
    expect(component.formatPercent('0.05')).toBe('5.00%');
  });

  it('should start with approval modal hidden', () => {
    expect(component.showApprovalModal).toBe(false);
    expect(component.selectedApproval).toBeNull();
  });

  it('should open approval modal', () => {
    const mockOrder = { id: '1', symbol: 'BTCUSDT' };
    component.openApproval(mockOrder);
    expect(component.showApprovalModal).toBe(true);
    expect(component.selectedApproval).toBe(mockOrder);
  });

  it('should close modal on onModalClosed', () => {
    component.showApprovalModal = true;
    component.selectedApproval = { id: '1' };
    component.onModalClosed();
    expect(component.showApprovalModal).toBe(false);
    expect(component.selectedApproval).toBeNull();
  });
});
