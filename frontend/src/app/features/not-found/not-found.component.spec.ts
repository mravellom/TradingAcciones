import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NotFoundComponent } from './not-found.component';

describe('NotFoundComponent', () => {
  let component: NotFoundComponent;
  let fixture: ComponentFixture<NotFoundComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NotFoundComponent],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(NotFoundComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display 404', () => {
    const compiled = fixture.nativeElement;
    expect(compiled.querySelector('.error-page__code').textContent).toContain('404');
  });

  it('should have link to dashboard', () => {
    const compiled = fixture.nativeElement;
    expect(compiled.querySelector('.error-page__link').getAttribute('href')).toBe('/');
  });
});
