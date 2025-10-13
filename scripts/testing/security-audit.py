#!/usr/bin/env python3
"""
ZeroQue Security Audit Script
Comprehensive security audit for all microservices
"""

import os
import sys
import json
import subprocess
import requests
from datetime import datetime
from typing import Dict, List, Any
import argparse

class SecurityAuditor:
    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
        self.services = [
            {"name": "orders", "port": 8080},
            {"name": "identity", "port": 8085},
            {"name": "ledger", "port": 8086},
            {"name": "payments", "port": 8087},
            {"name": "events", "port": 8088},
            {"name": "cv-gateway", "port": 8000},
            {"name": "cv-connector", "port": 8100},
            {"name": "approvals", "port": 8213},
            {"name": "entitlements", "port": 8211},
            {"name": "subscriptions", "port": 8212},
            {"name": "notifications", "port": 8300},
            {"name": "reports", "port": 8400},
            {"name": "usage", "port": 8200},
            {"name": "observability", "port": 8600},
            {"name": "service-registry", "port": 8500},
            {"name": "monitoring", "port": 8700}
        ]
        self.audit_results = {
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "summary": {
                "total_services": len(self.services),
                "passed": 0,
                "failed": 0,
                "warnings": 0,
                "critical_issues": []
            }
        }

    def run_audit(self) -> Dict[str, Any]:
        """Run comprehensive security audit"""
        print("🔒 Starting ZeroQue Security Audit...")
        print(f"📊 Auditing {len(self.services)} services")
        print("=" * 60)
        
        for service in self.services:
            print(f"\n🔍 Auditing {service['name']} service...")
            service_results = self._audit_service(service)
            self.audit_results["services"][service["name"]] = service_results
            
            # Update summary
            if service_results["status"] == "PASS":
                self.audit_results["summary"]["passed"] += 1
            elif service_results["status"] == "FAIL":
                self.audit_results["summary"]["failed"] += 1
                if service_results.get("critical_issues"):
                    self.audit_results["summary"]["critical_issues"].extend(
                        service_results["critical_issues"]
                    )
            else:
                self.audit_results["summary"]["warnings"] += 1
        
        self._generate_report()
        return self.audit_results

    def _audit_service(self, service: Dict[str, Any]) -> Dict[str, Any]:
        """Audit individual service"""
        service_url = f"{self.base_url}:{service['port']}"
        results = {
            "service": service["name"],
            "url": service_url,
            "status": "UNKNOWN",
            "checks": {},
            "critical_issues": [],
            "warnings": [],
            "recommendations": []
        }
        
        try:
            # 1. Health Check
            results["checks"]["health_check"] = self._check_health(service_url)
            
            # 2. Authentication & Authorization
            results["checks"]["auth_security"] = self._check_auth_security(service_url)
            
            # 3. Input Validation
            results["checks"]["input_validation"] = self._check_input_validation(service_url)
            
            # 4. Rate Limiting
            results["checks"]["rate_limiting"] = self._check_rate_limiting(service_url)
            
            # 5. CORS Configuration
            results["checks"]["cors_security"] = self._check_cors_security(service_url)
            
            # 6. Headers Security
            results["checks"]["security_headers"] = self._check_security_headers(service_url)
            
            # 7. SSL/TLS Configuration
            results["checks"]["ssl_security"] = self._check_ssl_security(service_url)
            
            # 8. Error Handling
            results["checks"]["error_handling"] = self._check_error_handling(service_url)
            
            # 9. Logging & Monitoring
            results["checks"]["logging_security"] = self._check_logging_security(service_url)
            
            # 10. Data Exposure
            results["checks"]["data_exposure"] = self._check_data_exposure(service_url)
            
            # Determine overall status
            results["status"] = self._determine_status(results["checks"])
            
        except Exception as e:
            results["status"] = "ERROR"
            results["error"] = str(e)
            results["critical_issues"].append(f"Service unreachable: {e}")
        
        return results

    def _check_health(self, service_url: str) -> Dict[str, Any]:
        """Check service health endpoint"""
        try:
            response = requests.get(f"{service_url}/health", timeout=5)
            return {
                "status": "PASS" if response.status_code == 200 else "FAIL",
                "response_code": response.status_code,
                "details": "Health endpoint accessible"
            }
        except Exception as e:
            return {
                "status": "FAIL",
                "error": str(e),
                "details": "Health endpoint not accessible"
            }

    def _check_auth_security(self, service_url: str) -> Dict[str, Any]:
        """Check authentication and authorization"""
        issues = []
        warnings = []
        
        # Test unprotected endpoints
        unprotected_endpoints = ["/health", "/metrics", "/docs", "/openapi.json"]
        
        for endpoint in unprotected_endpoints:
            try:
                response = requests.get(f"{service_url}{endpoint}", timeout=5)
                if endpoint == "/metrics" and response.status_code == 200:
                    issues.append(f"Metrics endpoint unprotected: {endpoint}")
            except:
                pass
        
        # Test protected endpoints without auth
        protected_endpoints = ["/orders/v4", "/users", "/payments/v4/intent"]
        
        for endpoint in protected_endpoints:
            try:
                response = requests.get(f"{service_url}{endpoint}", timeout=5)
                if response.status_code == 200:
                    issues.append(f"Protected endpoint accessible without auth: {endpoint}")
                elif response.status_code == 401:
                    warnings.append(f"Endpoint properly protected: {endpoint}")
            except:
                pass
        
        return {
            "status": "PASS" if not issues else "FAIL",
            "issues": issues,
            "warnings": warnings,
            "details": f"Found {len(issues)} auth issues, {len(warnings)} proper protections"
        }

    def _check_input_validation(self, service_url: str) -> Dict[str, Any]:
        """Check input validation"""
        issues = []
        
        # Test SQL injection attempts
        sql_payloads = ["'; DROP TABLE users; --", "1' OR '1'='1", "'; SELECT * FROM users; --"]
        
        for payload in sql_payloads:
            try:
                response = requests.post(f"{service_url}/orders/v4", 
                                       json={"tenant_id": payload}, 
                                       timeout=5)
                if response.status_code == 200:
                    issues.append(f"Potential SQL injection vulnerability with payload: {payload}")
            except:
                pass
        
        # Test XSS attempts
        xss_payloads = ["<script>alert('xss')</script>", "javascript:alert('xss')", "onload=alert('xss')"]
        
        for payload in xss_payloads:
            try:
                response = requests.post(f"{service_url}/orders/v4", 
                                       json={"description": payload}, 
                                       timeout=5)
                if response.status_code == 200:
                    issues.append(f"Potential XSS vulnerability with payload: {payload}")
            except:
                pass
        
        return {
            "status": "PASS" if not issues else "FAIL",
            "issues": issues,
            "details": f"Found {len(issues)} input validation issues"
        }

    def _check_rate_limiting(self, service_url: str) -> Dict[str, Any]:
        """Check rate limiting implementation"""
        issues = []
        
        # Test rapid requests
        try:
            for i in range(100):  # Send 100 rapid requests
                response = requests.get(f"{service_url}/health", timeout=1)
                if response.status_code == 429:
                    break
            else:
                issues.append("No rate limiting detected on health endpoint")
        except:
            pass
        
        return {
            "status": "PASS" if not issues else "WARN",
            "issues": issues,
            "details": "Rate limiting check completed"
        }

    def _check_cors_security(self, service_url: str) -> Dict[str, Any]:
        """Check CORS configuration"""
        issues = []
        
        try:
            response = requests.options(f"{service_url}/orders/v4", 
                                      headers={"Origin": "https://malicious.com"}, 
                                      timeout=5)
            
            cors_headers = {
                "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
                "Access-Control-Allow-Methods": response.headers.get("Access-Control-Allow-Methods"),
                "Access-Control-Allow-Headers": response.headers.get("Access-Control-Allow-Headers")
            }
            
            if cors_headers["Access-Control-Allow-Origin"] == "*":
                issues.append("CORS allows all origins (*)")
            elif cors_headers["Access-Control-Allow-Origin"] == "https://malicious.com":
                issues.append("CORS allows arbitrary origins")
                
        except Exception as e:
            issues.append(f"CORS check failed: {e}")
        
        return {
            "status": "PASS" if not issues else "WARN",
            "issues": issues,
            "details": "CORS configuration check completed"
        }

    def _check_security_headers(self, service_url: str) -> Dict[str, Any]:
        """Check security headers"""
        required_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options", 
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Content-Security-Policy"
        ]
        
        missing_headers = []
        
        try:
            response = requests.get(f"{service_url}/health", timeout=5)
            
            for header in required_headers:
                if header not in response.headers:
                    missing_headers.append(header)
                    
        except Exception as e:
            missing_headers.append(f"Header check failed: {e}")
        
        return {
            "status": "PASS" if not missing_headers else "WARN",
            "missing_headers": missing_headers,
            "details": f"Missing {len(missing_headers)} security headers"
        }

    def _check_ssl_security(self, service_url: str) -> Dict[str, Any]:
        """Check SSL/TLS configuration"""
        # This would require SSL implementation
        return {
            "status": "INFO",
            "details": "SSL check requires HTTPS implementation"
        }

    def _check_error_handling(self, service_url: str) -> Dict[str, Any]:
        """Check error handling"""
        issues = []
        
        # Test error endpoints
        try:
            response = requests.get(f"{service_url}/nonexistent", timeout=5)
            
            # Check if sensitive information is exposed in errors
            response_text = response.text.lower()
            sensitive_keywords = ["password", "token", "secret", "key", "database", "sql"]
            
            for keyword in sensitive_keywords:
                if keyword in response_text:
                    issues.append(f"Sensitive information exposed in error: {keyword}")
                    
        except:
            pass
        
        return {
            "status": "PASS" if not issues else "FAIL",
            "issues": issues,
            "details": f"Found {len(issues)} error handling issues"
        }

    def _check_logging_security(self, service_url: str) -> Dict[str, Any]:
        """Check logging and monitoring security"""
        # This would require access to logs
        return {
            "status": "INFO",
            "details": "Logging security check requires log access"
        }

    def _check_data_exposure(self, service_url: str) -> Dict[str, Any]:
        """Check for data exposure"""
        issues = []
        
        # Check if sensitive data is exposed in responses
        try:
            response = requests.get(f"{service_url}/metrics", timeout=5)
            
            if response.status_code == 200:
                # Check for sensitive data in metrics
                response_text = response.text.lower()
                sensitive_patterns = ["password", "secret", "token", "key"]
                
                for pattern in sensitive_patterns:
                    if pattern in response_text:
                        issues.append(f"Sensitive data in metrics: {pattern}")
                        
        except:
            pass
        
        return {
            "status": "PASS" if not issues else "FAIL",
            "issues": issues,
            "details": f"Found {len(issues)} data exposure issues"
        }

    def _determine_status(self, checks: Dict[str, Any]) -> str:
        """Determine overall service status"""
        fail_count = sum(1 for check in checks.values() if check.get("status") == "FAIL")
        warn_count = sum(1 for check in checks.values() if check.get("status") == "WARN")
        
        if fail_count > 0:
            return "FAIL"
        elif warn_count > 2:
            return "WARN"
        else:
            return "PASS"

    def _generate_report(self):
        """Generate security audit report"""
        print("\n" + "=" * 60)
        print("🔒 ZEROQUE SECURITY AUDIT REPORT")
        print("=" * 60)
        
        summary = self.audit_results["summary"]
        print(f"📊 Total Services: {summary['total_services']}")
        print(f"✅ Passed: {summary['passed']}")
        print(f"❌ Failed: {summary['failed']}")
        print(f"⚠️  Warnings: {summary['warnings']}")
        
        if summary["critical_issues"]:
            print(f"\n🚨 CRITICAL ISSUES:")
            for issue in summary["critical_issues"]:
                print(f"   • {issue}")
        
        print(f"\n📋 DETAILED RESULTS:")
        for service_name, results in self.audit_results["services"].items():
            status_emoji = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "ERROR": "🔥"}.get(results["status"], "❓")
            print(f"   {status_emoji} {service_name}: {results['status']}")
            
            if results.get("critical_issues"):
                for issue in results["critical_issues"]:
                    print(f"      🚨 {issue}")
        
        # Save report to file
        report_file = f"security-audit-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.audit_results, f, indent=2)
        
        print(f"\n📄 Detailed report saved to: {report_file}")

def main():
    parser = argparse.ArgumentParser(description="ZeroQue Security Audit Tool")
    parser.add_argument("--base-url", default="http://localhost", help="Base URL for services")
    parser.add_argument("--output", help="Output file for JSON report")
    
    args = parser.parse_args()
    
    auditor = SecurityAuditor(args.base_url)
    results = auditor.run_audit()
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n📄 Report saved to: {args.output}")
    
    # Exit with error code if critical issues found
    if results["summary"]["critical_issues"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
