import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from app.config.constants import Constants, ErrorMessage, HttpMethods


class BaseLLMProvider(ABC):
    """
    Mirrors BaseConnectorClass pattern.
    Owns all HTTP mechanics: request execution, retry logic, response envelope.
    Subclasses own: base_url, headers, payload construction, response parsing.
    """

    async def request_handler(self,
                               method: str,
                               url: str,
                               payload_json: dict = None,
                               query_params: dict = None,
                               headers: dict = None,
                               timeout: int = None,
                               retry_count: int = None,
                               retry_wait: int = None) -> dict:
        try:
            if not timeout:
                timeout = 30

            if not retry_wait:
                retry_wait = 15

            if not retry_count:
                retry_count = 0

            if retry_count > 10:
                raise Exception("Retry count cannot be greater than 10")

            if retry_wait > 60:
                raise Exception("Retry wait cannot be greater than 60 seconds")

            if method not in [m.value for m in HttpMethods]:
                return {
                    Constants.ACTION_RESULT: ErrorMessage.INVALID_METHOD,
                    Constants.ACTION_STATUS: Constants.ERROR
                }

            response = await self.make_request(
                method=method,
                url=url,
                payload_json=payload_json,
                query_params=query_params,
                headers=headers,
                timeout=timeout,
                retry_count=retry_count,
                retry_wait=retry_wait
            )

            if not isinstance(response, dict):
                response = self.process_response(response)

            return response

        except Exception as e:
            return {Constants.ACTION_RESULT: str(e), Constants.ACTION_STATUS: Constants.ERROR}

    async def make_request(self,
                           method: str,
                           url: str,
                           payload_json: dict = None,
                           query_params: dict = None,
                           headers: dict = None,
                           timeout: int = 30,
                           retry_count: int = 0,
                           retry_wait: int = 15) -> httpx.Response | dict:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    json=payload_json,
                    params=query_params,
                    headers=headers,
                    timeout=timeout
                )

            if response.status_code >= 500:
                if retry_count > 0:
                    await asyncio.sleep(retry_wait)
                    return await self.make_request(
                        method=method,
                        url=url,
                        payload_json=payload_json,
                        query_params=query_params,
                        headers=headers,
                        timeout=timeout,
                        retry_count=retry_count - 1,
                        retry_wait=retry_wait
                    )

            return response

        except Exception as e:
            return {Constants.ACTION_RESULT: str(e), Constants.ACTION_STATUS: Constants.ERROR}

    async def make_stream_request(self,
                                  url: str,
                                  payload_json: dict,
                                  headers: dict,
                                  timeout: int = 120) -> AsyncGenerator[str, None]:
        """
        No retry on stream requests — cannot retry mid-flight.
        Yields raw line strings; provider subclass parses them.
        """
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload_json, headers=headers, timeout=timeout) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line

    def process_response(self, response: httpx.Response) -> dict:
        response_data = {Constants.STATUS_CODE: response.status_code}
        try:
            if response.is_success:
                if not response.text:
                    response_data[Constants.RESPONSE] = ErrorMessage.NO_DATA_RETURNED
                else:
                    try:
                        response_data[Constants.RESPONSE] = response.json()
                    except Exception:
                        response_data[Constants.RESPONSE] = response.text
                execution_status = Constants.SUCCESS
            else:
                try:
                    response_data[Constants.RESPONSE] = response.json()
                except Exception:
                    response_data[Constants.RESPONSE] = response.text
                execution_status = Constants.ERROR

        except Exception as e:
            response_data[Constants.RESPONSE] = str(e)
            execution_status = Constants.ERROR

        return {Constants.ACTION_RESULT: response_data, Constants.ACTION_STATUS: execution_status}

    async def test_connection(self, url: str, headers: dict, timeout: int) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=timeout)
        except Exception as e:
            return {
                Constants.MESSAGE: ErrorMessage.CONNECTION_FAILED,
                Constants.ACTION_RESULT: str(e),
                Constants.ACTION_STATUS: Constants.ERROR
            }

        try:
            response.raise_for_status()
        except Exception as e:
            result = {
                Constants.MESSAGE: ErrorMessage.AUTH_FAILED,
                Constants.STATUS_CODE: response.status_code,
                Constants.ACTION_STATUS: Constants.ERROR
            }
            try:
                result[Constants.ACTION_RESULT] = response.json()
            except Exception:
                result[Constants.ACTION_RESULT] = response.text or str(e)
            return result

        return {
            Constants.MESSAGE: Constants.AUTH_SUCCESSFUL,
            Constants.STATUS_CODE: response.status_code,
            Constants.ACTION_RESULT: Constants.CREDENTIALS_VALID,
            Constants.ACTION_STATUS: Constants.SUCCESS
        }

    @abstractmethod
    async def generate(self, messages: list, model: str, temperature: float, max_tokens: int) -> dict:
        ...

    @abstractmethod
    async def stream(self, messages: list, model: str, temperature: float, max_tokens: int) -> AsyncGenerator[str, None]:
        ...
