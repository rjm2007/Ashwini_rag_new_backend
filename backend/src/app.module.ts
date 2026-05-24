import { MiddlewareConsumer, Module, NestModule } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { DatabaseModule } from "./database/database.module";
import { AuthMiddleware } from "./common/middleware/auth.middleware";
import { AuthModule } from "./modules/auth/auth.module";
import { DocumentsModule } from "./modules/documents/documents.module";
import { ReviewModule } from "./modules/review/review.module";
import { QueryModule } from "./modules/query/query.module";
import { DashboardModule } from "./modules/dashboard/dashboard.module";

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    DatabaseModule,
    AuthModule,
    DocumentsModule,
    ReviewModule,
    QueryModule,
    DashboardModule
  ]
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    // This function applies auth middleware to all endpoints except login.
    consumer.apply(AuthMiddleware).exclude("auth/login").forRoutes("*");
  }
}
