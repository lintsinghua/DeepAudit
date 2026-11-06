/*
 * Trimmed Juice Shop server for benchmarking: registers only the routes kept in routes/.
 * Route registrations are copied from the original server.ts (commit 717f5ef).
 *
 * Derived from OWASP Juice Shop.
 * Copyright (c) 2014-2026 Bjoern Kimminich & the OWASP Juice Shop contributors.
 * SPDX-License-Identifier: MIT
 */
import express from 'express'
import multer from 'multer'
import serveIndex from 'serve-index'
import * as utils from './lib/utils'
import * as security from './lib/insecurity'
import { login } from './routes/login'
import { searchProducts } from './routes/search'
import { updateProductReviews } from './routes/updateProductReviews'
import { likeProductReviews } from './routes/likeProductReviews'
import { showProductReviews } from './routes/showProductReviews'
import { performRedirect } from './routes/redirect'
import { trackOrder } from './routes/trackOrder'
import { b2bOrder } from './routes/b2bOrder'
import { getUserProfile } from './routes/userProfile'
import { updateUserProfile } from './routes/updateUserProfile'
import { ensureFileIsPassed, handleZipFileUpload, checkUploadSize, checkFileType, handleXmlUpload, handleYamlUpload } from './routes/fileUpload'
import { profileImageUrlUpload } from './routes/profileImageUrlUpload'
import dataErasure from './routes/dataErasure'
import { servePublicFiles } from './routes/fileServer'
import { serveKeyFiles } from './routes/keyServer'
import { serveLogFiles } from './routes/logfileServer'
import { serveQuarantineFiles } from './routes/quarantineServer'
import { captchas } from './routes/captcha'
import { retrieveBasket } from './routes/basket'
import * as address from './routes/address'
import * as delivery from './routes/delivery'

const app = express()
const uploadToMemory = multer({ storage: multer.memoryStorage(), limits: { fileSize: 200000 } })

app.use(express.json())
app.use(express.urlencoded({ extended: true }))

/* Authorization (copied from the original server.ts for the routes kept here) */
app.use(security.updateAuthenticatedUsers())
app.use('/rest/basket', security.isAuthorized(), security.appendUserId())
app.use('/rest/basket/:id', security.isAuthorized())
app.use('/b2b/v2', security.isAuthorized())

/* /ftp directory browsing and file download */
app.use('/ftp', serveIndex('ftp', { icons: true }))
app.use('/ftp(?!/quarantine)/:file', servePublicFiles())
app.use('/ftp/quarantine/:file', serveQuarantineFiles())

/* /encryptionkeys directory browsing */
app.use('/encryptionkeys', serveIndex('encryptionkeys', { icons: true, view: 'details' }))
app.use('/encryptionkeys/:file', serveKeyFiles())

/* /logs directory browsing */
app.use('/support/logs', serveIndex('logs', { icons: true, view: 'details' }))
app.use('/support/logs/:file', serveLogFiles())
app.post('/file-upload', uploadToMemory.single('file'), ensureFileIsPassed, checkUploadSize, checkFileType, handleZipFileUpload, handleXmlUpload, handleYamlUpload)
app.post('/profile/image/url', uploadToMemory.single('file'), utils.asyncHandler(profileImageUrlUpload()))
app.get('/api/Addresss', security.appendUserId(), utils.asyncHandler(address.getAddress()))
app.get('/api/Addresss/:id', security.appendUserId(), utils.asyncHandler(address.getAddressById()))
app.get('/api/Deliverys', utils.asyncHandler(delivery.getDeliveryMethods()))
app.post('/rest/user/login', login())
app.get('/rest/products/search', utils.asyncHandler(searchProducts()))
app.get('/rest/basket/:id', utils.asyncHandler(retrieveBasket()))
app.get('/rest/captcha', utils.asyncHandler(captchas()))
app.get('/rest/track-order/:id', trackOrder())
app.get('/rest/products/:id/reviews', showProductReviews())
app.patch('/rest/products/reviews', security.isAuthorized(), updateProductReviews())
app.post('/rest/products/reviews', security.isAuthorized(), utils.asyncHandler(likeProductReviews()))
app.post('/b2b/v2/orders', b2bOrder())
app.use('/dataerasure', dataErasure)
app.get('/redirect', performRedirect())
app.get('/profile', utils.asyncHandler(getUserProfile()))
app.post('/profile', utils.asyncHandler(updateUserProfile()))

app.listen(3000)
