Analyze this shopping receipt image.
Return only valid JSON, without markdown fences or extra commentary.
Schema:
{
  "store": "store name or null",
  "date": "receipt date or null",
  "total": "numeric total amount or null",
  "currency": "currency symbol/code or null",
  "items": [
    {"name": "item name", "quantity": "quantity or null", "price": "numeric price or null"}
  ]
}
Use null when a field is not visible.
